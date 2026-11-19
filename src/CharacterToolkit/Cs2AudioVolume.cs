using System.Text.Json;
using System.Text.Json.Nodes;
using Avalonia.Controls;
using Avalonia.Layout;
namespace SekiroCharacterToolkit;
public partial class MainWindow
{
 readonly NumericUpDown cs2BatchVolume=new(){Minimum=0,Maximum=10,Increment=.5m,Value=2,Width=105,FormatString="0.00"};
 readonly Dictionary<string,Dictionary<string,decimal>> cs2VolumeProfiles=new(StringComparer.OrdinalIgnoreCase);
 readonly Dictionary<string,string> cs2AudioInfo=new();
 readonly HashSet<string> cs2MixedVolumes=new();
 string? cs2VolumeScope;
 string VolumeScope()=>Path.GetFullPath(string.IsNullOrWhiteSpace(Value("cs2_addon"))?home:Value("cs2_addon"))+"|"+Value("cs2_name")+"|"+Value("cs2_package");
 Dictionary<string,decimal> Volumes()
 {
  var key=VolumeScope();
  if(!cs2VolumeProfiles.TryGetValue(key,out var values)){values=new();cs2VolumeProfiles[key]=values;}
  return values;
 }
 void InitAudioVolumes(Dictionary<string,string>? saved)
 {
  if(saved?.TryGetValue("cs2_volume_profiles",out var json)==true)
  {
   try{var profiles=JsonSerializer.Deserialize<Dictionary<string,Dictionary<string,decimal>>>(json);
    if(profiles!=null)foreach(var (scope,values) in profiles)cs2VolumeProfiles[scope]=values.Where(p=>p.Value>=0&&p.Value<=10).ToDictionary();
   }catch(JsonException){}
  }
 }
 void BeginVolumeList(){cs2VolumeScope=VolumeScope();cs2AudioInfo.Clear();cs2MixedVolumes.Clear();}
 void RequireVolumeContext()
 {if(cs2VolumeScope!=VolumeScope())throw new Exception("目录或模型名已改变，请重新加载动作列表，避免将音量应用到其他角色");}
 Control AudioVolumeControls()=>Stack(
  Text("每个动作独立音量：0 静音 · 1 原始音量 · 2 两倍 · 最大 10。设置为绝对倍数，不会反复叠加。",12,"#93A9BC"),
  Row(Text("批量音量"),cs2BatchVolume,Button("应用到勾选动作",SetSelectedAudioVolume),Button("加载现有模型音量",()=>_=Run(LoadExistingAudioVolumes))),
  Row(Button("仅更新勾选动作音量",()=>_=Run(UpdateAudioVolumes)),Text("无需重烘模型或重新转码音频；沿用下方编译选项，自动备份。",12,"#93A9BC")));
 void SetSelectedAudioVolume()
 {
  RequireVolumeContext();var value=cs2BatchVolume.Value??throw new Exception("请输入音量");
  foreach(var key in cs2Selected.Where(p=>p.Value).Select(p=>p.Key)){Volumes()[key]=value;cs2MixedVolumes.Remove(key);}
  RefreshCs2Clips();SaveSettings();
 }
 Control AudioClipRow(string name,bool selected)
 {
  var check=new CheckBox{Content=name,IsChecked=selected,MinWidth=315};
  check.IsCheckedChanged+=(_,_)=>cs2Selected[name]=check.IsChecked==true;
  var values=Volumes();var mixed=cs2MixedVolumes.Contains(name);
  var input=new NumericUpDown{Minimum=0,Maximum=10,Increment=.25m,Value=mixed?null:values.GetValueOrDefault(name,1m),Width=110,FormatString="0.00"};
  ToolTip.SetTip(input,"CS2 声音事件音量倍数；共用音效会生成动作专属事件，不影响其他动作");
  input.ValueChanged+=(_,_)=>{if(input.Value is decimal value){values[name]=value;cs2MixedVolumes.Remove(name);}};
  return Row(check,input,Text("倍"),Text(mixed?"混合音量（设置后统一）":cs2AudioInfo.GetValueOrDefault(name,""),12,"#93A9BC"));
 }
 string WriteAudioVolumes(bool selectedOnly)
 {
  RequireVolumeContext();var values=Volumes();var result=new Dictionary<string,decimal>();
  foreach(var (key,value) in values)if(!selectedOnly||cs2Selected.GetValueOrDefault(key))result[key]=value;
  if(selectedOnly)foreach(var (key,selected) in cs2Selected)if(selected)
  {if(cs2MixedVolumes.Contains(key))throw new Exception("动作包含不同音量，请先设置该动作音量："+key);result.TryAdd(key,1m);}
  if(selectedOnly&&result.Count==0)throw new Exception("请勾选需要调整音量的动作");
  var path=Path.Combine(activeTaskCache??Value("cache"),"audio_volumes_"+Guid.NewGuid().ToString("N")+".json");
  Directory.CreateDirectory(Path.GetDirectoryName(path)!);File.WriteAllText(path,JsonSerializer.Serialize(result));return path;
 }
 async Task LoadExistingAudioVolumes()
 {
  var path=Path.Combine(activeTaskCache??Value("cache"),"existing_audio_volumes.json");
  await Python("cs2_audio_volume.py","--addon",Value("cs2_addon"),"--name",Value("cs2_name"),"--inspect",path);
  var result=JsonNode.Parse(File.ReadAllText(path))!;BeginVolumeList();cs2Selected.Clear();var values=Volumes();
  foreach(var clip in result["clips"]!.AsArray())
  {
   var key=clip!["source"]!.GetValue<string>();cs2Selected[key]=true;
   var count=clip["events"]!.GetValue<int>();cs2AudioInfo[key]=count==0?"无音频事件":$"{count} 个声音事件";
   if(clip["volume"] is JsonNode v)values[key]=v.GetValue<decimal>();
   else if(clip["mixed"]?.GetValue<bool>()==true){values.Remove(key);cs2MixedVolumes.Add(key);}
  }
  cs2LoadedPackage=string.IsNullOrWhiteSpace(Value("cs2_package"))?null:Path.GetFullPath(Value("cs2_package"));
  cs2All.IsChecked=false;RefreshCs2Clips();SaveSettings();Log($"已读取现有模型 {cs2Selected.Count} 个动作的实际声音事件音量；不改写文件");
 }
 async Task UpdateAudioVolumes()
 {
  var argv=new List<string>{"--addon",Value("cs2_addon"),"--name",Value("cs2_name"),"--volumes",WriteAudioVolumes(true)};
  if(cs2Compile.IsChecked==true)argv.Add("--compile");
  await Python("cs2_audio_volume.py",argv.ToArray());
  var report=JsonNode.Parse(File.ReadAllText(Path.Combine(Cs2ResourceDir("rawmodels"),"reports/audio_volume.json")))!;
  if(report["passed"]?.GetValue<bool>()!=true)throw new Exception("音量更新未通过，请查看报告");
  SaveSettings();status.Text=cs2Compile.IsChecked==true?"音量已更新并编译 · 重新打开 ModelDoc 试听":"音量源文件已更新 · 请在 Workshop Tools 编译后试听";Log(report.ToJsonString());
 }
}
