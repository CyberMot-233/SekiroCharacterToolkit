using System.Text.Json;
using System.Text.Json.Nodes;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Platform.Storage;
namespace SekiroCharacterToolkit;
public partial class MainWindow
{
 readonly CheckBox cs2X=new(){Content="TX",IsChecked=true},cs2Y=new(){Content="TY",IsChecked=true},cs2Z=new(){Content="TZ"},cs2R=new(){Content="RZ"};
 readonly CheckBox cs2Audio=new(){Content="动作声音事件 + CS2 音频（保留原 MP3）",IsChecked=true};
 readonly CheckBox cs2Compile=new(){Content="使用此项目安装的 Workshop Tools 编译",IsChecked=true};
 readonly CheckBox cs2All=new(){Content="转换全部动作",IsChecked=true};
 readonly CheckBox cs2AfterExport=new(){Content="提取完成后自动转换 CS2（使用转换页的目录与选项）"};
 readonly TextBox cs2Search=new(){Watermark="筛选动作名称（不改变勾选）"};
 readonly StackPanel cs2Clips=new(){Spacing=2};
 readonly ScrollViewer cs2ClipScroll=new(){Height=165};
 readonly Dictionary<string,bool> cs2Selected=new(); string? cs2LoadedPackage;
 void InitCs2(Dictionary<string,string>? saved)
 {
  // Keep the presenter together with its content across page rebuilds. A new
  // ScrollViewer cannot adopt content still owned by the previous presenter.
  cs2ClipScroll.Content=cs2Clips;
  foreach(var (key,val) in new Dictionary<string,string>{{"cs2_package",""},{"cs2_addon",""},{"cs2_name","wolf"}})
   fields[key]=new TextBox{Text=saved?.GetValueOrDefault(key,val)??val,MinWidth=280};
  var axes=saved?.GetValueOrDefault("cs2_axes","xy")??"xy";cs2X.IsChecked=axes.Contains('x');cs2Y.IsChecked=axes.Contains('y');cs2Z.IsChecked=axes.Contains('z');cs2R.IsChecked=axes.Contains('r');
  cs2Audio.IsChecked=saved?.GetValueOrDefault("cs2_audio","true")!="false";cs2Compile.IsChecked=saved?.GetValueOrDefault("cs2_compile","true")!="false";cs2AfterExport.IsChecked=saved?.GetValueOrDefault("cs2_after_export","false")=="true";
  InitAudioVolumes(saved);
  cs2Search.TextChanged+=(_,_)=>RefreshCs2Clips();
  Opened+=async (_,_)=>
  {
   if(!args.Contains("--e2e-cs2"))return;
   var prior=File.Exists(config)?File.ReadAllText(config):null;
   await Run(async()=>
   {
    string Arg(string key){var i=Array.IndexOf(args,key);return i>=0&&i+1<args.Length?args[i+1]:throw new Exception("Missing test argument "+key);}
    fields["cs2_package"].Text=Arg("--test-package");fields["cs2_addon"].Text=Arg("--test-addon");fields["cs2_name"].Text="sct_test_c1010";
    cs2Audio.IsChecked=false;cs2Compile.IsChecked=true;cs2All.IsChecked=false;
    await LoadCs2Clips();var chosen=cs2Selected.Keys.Where((_,i)=>i==0||i==cs2Selected.Count-1).ToHashSet();
    foreach(var key in cs2Selected.Keys.ToArray())cs2Selected[key]=chosen.Contains(key);
    ShowCs2();await ConvertCs2(args.Contains("--test-repair"));
   });
   Directory.CreateDirectory(Path.Combine(home,"tests","cs2_101"));
   File.WriteAllText(Path.Combine(home,"tests","cs2_101",args.Contains("--test-repair")?"ui_repair.json":"ui_e2e.json"),JsonSerializer.Serialize(new{result=status.Text,package=Value("cs2_package"),selected=cs2Selected.Where(x=>x.Value).Select(x=>x.Key)}));
   Close();if(prior!=null)File.WriteAllText(config,prior);
  };
 }
 string Cs2Axes()=>(cs2X.IsChecked==true?"x":"")+(cs2Y.IsChecked==true?"y":"")+(cs2Z.IsChecked==true?"z":"")+(cs2R.IsChecked==true?"r":"");
 void SaveCs2(Dictionary<string,string?> settings)
 {settings["cs2_volume_profiles"]=JsonSerializer.Serialize(cs2VolumeProfiles);settings["cs2_axes"]=Cs2Axes();settings["cs2_audio"]=cs2Audio.IsChecked==true?"true":"false";settings["cs2_compile"]=cs2Compile.IsChecked==true?"true":"false";settings["cs2_after_export"]=cs2AfterExport.IsChecked==true?"true":"false";}
 void ShowCs2()
 {
  page.Content=null;
  Show(Card(Stack(Text("转换为 CS2 模型",24),
   Text("原生提取包 → DMX 骨架 / 动作 → VMAT / RGB PNG → VMDL / 声音事件 → 编译。保留只狼原动作，用于 prop_dynamic；不是玩家动作重定向。",12,"#93A9BC"),
   PathField("角色提取包目录","cs2_package"),PathField("CS2 content/addon","cs2_addon"),
   Row(Text("模型资源名（英文）"),fields["cs2_name"],Button("使用最近导出",()=>{if(lastJob!=null)fields["cs2_package"].Text=lastJob;})),
   Row(Button("加载动作列表",()=>_=Run(LoadCs2Clips)),cs2All,Button("列表全选",()=>{foreach(var k in cs2Selected.Keys.ToArray())cs2Selected[k]=true;RefreshCs2Clips();}),Button("列表清空",()=>{foreach(var k in cs2Selected.Keys.ToArray())cs2Selected[k]=false;RefreshCs2Clips();})),
   cs2Search,cs2ClipScroll,AudioVolumeControls(),
   Row(Text("CS2 ExtractMotion："),cs2X,cs2Y,cs2Z,cs2R),
   Text("在 ModelDoc 内提取所选轴的根运动；不会改写 E 盘的 Blender 工程。默认限制平面移动，保留跳跃高度和转向。",12,"#93A9BC"),
   Row(cs2Audio,cs2Compile),
   Row(Button("转换并生成 CS2 资源",()=>_=Run(()=>ConvertCs2()),true),Button("修复已完成的 CS2 模型",()=>_=Run(()=>ConvertCs2(true))),Button("打开模型目录",()=>Open(Cs2ResourceDir("models"))),Button("打开转换报告",()=>Open(Path.Combine(Cs2ResourceDir("rawmodels"),"reports")))),
   Row(Button("修复部件显隐（保留材质设置）",()=>_=Run(RepairCs2Visibility)),Text("备用武器悬空、衣装叠加或 BodyGroupList 被禁用时使用；不重新烘焙动作。",12,"#93A9BC")),
   Text("修复：仅复用已完成的统一绑定动作，备份旧 VMDL 后重建；不会恢复全量。自动避开 8×16 位蒙皮炸模格式，不删除角色骨架或裁掉武器权重。",12,"#93A9BC"),
   Text("分类：models/sekiro/characters · rawmodels/sekiro/characters · materials/sekiro/characters · sounds/sekiro/characters。编译产物由官方编译器写入对应 game/addon。",12,"#93A9BC"))));
 }
 string Cs2ResourceDir(string kind)=>Path.Combine(Value("cs2_addon"),kind,"sekiro","characters",Value("cs2_name"));
 async Task RepairCs2Visibility()
 {
  if(!System.Text.RegularExpressions.Regex.IsMatch(Value("cs2_name"),"^[a-z][a-z0-9_]*$"))throw new Exception("模型名使用小写英文字母、数字与下划线，字母开头");
  var argv=new List<string>{"--addon",Value("cs2_addon"),"--name",Value("cs2_name")};
  if(cs2Compile.IsChecked==true)argv.Add("--compile");
  await Python("cs2_repair_visibility.py",argv.ToArray());
  var report=JsonNode.Parse(File.ReadAllText(Path.Combine(Cs2ResourceDir("rawmodels"),"reports","visibility_repair.json")))!;
  if(report["passed"]?.GetValue<bool>()!=true)throw new Exception("部件显隐维修未通过，请查看报告");
  status.Text="部件显隐已修复 · 保留材质与动作 · 请重新打开 ModelDoc 文档";Log(report.ToJsonString());
 }
 Task LoadCs2Clips()
 {
  var p=Path.GetFullPath(Value("cs2_package"));var j=JsonNode.Parse(File.ReadAllText(Path.Combine(p,"package.json")))!;
  BeginVolumeList();cs2Selected.Clear();foreach(var c in j["clips"]!.AsArray())cs2Selected.Add(c!["name"]!.GetValue<string>(),true);
  cs2LoadedPackage=p;RefreshCs2Clips();Log($"CS2 动作列表：{cs2Selected.Count} 个");return Task.CompletedTask;
 }
 void RefreshCs2Clips()
 {
  cs2Clips.Children.Clear();var filter=cs2Search.Text??"";
  foreach(var (name,selected) in cs2Selected.Where(x=>x.Key.Contains(filter,StringComparison.OrdinalIgnoreCase)))
  {cs2Clips.Children.Add(AudioClipRow(name,selected));}
 }
 async Task ConvertCs2(bool repairOnly=false)
 {
  var p=Path.GetFullPath(Value("cs2_package"));if(!File.Exists(Path.Combine(p,"package.json")))throw new Exception("请选择包含 package.json 的角色提取目录");
  if(!System.Text.RegularExpressions.Regex.IsMatch(Value("cs2_name"),"^[a-z][a-z0-9_]*$"))throw new Exception("模型名使用小写英文字母、数字与下划线，字母开头");
  if(cs2Audio.IsChecked==true&&!File.Exists(Path.Combine(p,"audio","action_sounds.csv")))
   await Python("audio_extract.py","--package",p,"--root",Value("game"),"--dsas",Value("dsas"),"--ffmpeg",Value("ffmpeg"),"--language","jajp","--cache",activeTaskCache??Value("cache"),"--render");
  var axes=Cs2Axes();
  var a=new List<string>{"--package",p,"--addon",Value("cs2_addon"),"--name",Value("cs2_name"),"--motion-axes",axes,"--blender",Value("blender"),"--ffmpeg",Value("ffmpeg")};
  if(repairOnly)
  {
   var completed=Path.Combine(Cs2ResourceDir("rawmodels"),"compile_export.json");
   if(!File.Exists(completed))throw new Exception("没有已完成的统一绑定动作，请先转换所选动作。不会自动恢复全量。");
   a.Add("--reuse-bound-export");Log("仅修复已完成动作；不重新提取，不恢复未完成的全量绑定。");
  }
  if(!repairOnly&&cs2All.IsChecked!=true)
  {
   if(cs2LoadedPackage!=p)throw new Exception("请先加载当前提取包的动作列表");
   var selected=cs2Selected.Where(x=>x.Value).Select(x=>x.Key).ToArray();if(selected.Length==0)throw new Exception("没有选择动作");
   var path=Cache("cs2_selected_"+DateTime.Now.ToString("yyyyMMdd_HHmmss_fff")+".json");File.WriteAllText(path,JsonSerializer.Serialize(selected));a.AddRange(new[]{"--clip-list",path});
  }
  if(cs2Audio.IsChecked==true){a.Add("--audio");if(Volumes().Count>0){cs2VolumeScope=VolumeScope();a.AddRange(new[]{"--audio-volumes",WriteAudioVolumes(false)});}}if(cs2Compile.IsChecked==true)a.Add("--compile");
  await Python("cs2_convert.py",a.ToArray());var report=JsonNode.Parse(File.ReadAllText(Path.Combine(p,"cs2_conversion.json")))!;
  if(report["passed"]?.GetValue<bool>()==false)taskReportsPassed=false;status.Text="CS2："+report["status"]+" · "+report["actions"]+" 个动作（游戏内待验收）";Log(report.ToJsonString());
 }
}
