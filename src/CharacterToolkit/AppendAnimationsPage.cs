using System.Text.Json;
using System.Text.Json.Nodes;
using Avalonia.Controls;
namespace SekiroCharacterToolkit;
public partial class MainWindow
{
 readonly ComboBox appendTarget=new(){ItemsSource=new[]{"已有 Blender 工程","已有 CS2 模型"},SelectedIndex=0,Width=240};
 readonly CheckBox appendCompile=new(){Content="更新后编译 CS2 并回读校验",IsChecked=true};
 readonly CheckBox appendAudio=new(){Content="新增动作音频事件（覆盖动作保留原音量）",IsChecked=true};
 readonly TextBox appendSearch=new(){Watermark="筛选动作 ID（筛选不改变勾选）"};
 readonly StackPanel appendRows=new(){Spacing=3};readonly ScrollViewer appendScroll=new(){Height=240};
 readonly Dictionary<string,bool> appendSelected=new();readonly HashSet<string> appendExisting=new();string? appendContext;
 string AppendContext()=>Value("append_package")+"|"+appendTarget.SelectedIndex+"|"+Value("append_blend")+"|"+Value("append_addon")+"|"+Value("append_name");
 void InitAppend(Dictionary<string,string>? saved)
 {
  foreach(var (key,value) in new Dictionary<string,string>{{"append_package",""},{"append_blend",""},{"append_addon",""},{"append_name","wolf"}})fields[key]=new TextBox{Text=saved?.GetValueOrDefault(key,value)??value,MinWidth=280};
  appendTarget.SelectedIndex=saved?.GetValueOrDefault("append_target")=="cs2"?1:0;appendScroll.Content=appendRows;
  appendSearch.TextChanged+=(_,_)=>RefreshAppendRows();
 }
 void RefreshAppendRows()
 {
  appendRows.Children.Clear();foreach(var (name,selected) in appendSelected.Where(x=>x.Key.Contains(appendSearch.Text??"",StringComparison.OrdinalIgnoreCase)))
  {var c=new CheckBox{Content=name+(appendExisting.Contains(name)?"  · 已有，选中将覆盖":"  · 新增"),IsChecked=selected};c.IsCheckedChanged+=(_,_)=>appendSelected[name]=c.IsChecked==true;appendRows.Children.Add(c);}
 }
 void ShowAppendAnimations()
 {
  Show(Card(Stack(Text("追加 / 覆盖动画",24),Text("仅处理勾选动作：新动作加入原文件，同名动作覆盖，未选择动作保留；先备份，失败恢复。无需重新导出人物网格和材质。",12,"#93A9BC"),
   Row(appendTarget,Button("使用当前 CS2 设置",()=>{fields["append_package"].Text=Value("cs2_package");fields["append_addon"].Text=Value("cs2_addon");fields["append_name"].Text=Value("cs2_name");appendTarget.SelectedIndex=1;})),
   PathField("原角色提取包", "append_package"),PathField("目标 .blend 文件","append_blend",true),PathField("目标 CS2 addon","append_addon"),Row(Text("CS2 模型名"),fields["append_name"]),
   Text("Blender 选择具体 .blend（包括分批工程）；CS2 选择原 addon 与模型名。只需填写当前目标对应的路径。新增源动作从原 source_native 或设置中的游戏解包目录读取。",12,"#93A9BC"),
   Row(Button("加载可追加动作",()=>_=Run(LoadAppendActions)),Button("全选",()=>{foreach(var k in appendSelected.Keys.ToArray())appendSelected[k]=true;RefreshAppendRows();}),Button("清空",()=>{foreach(var k in appendSelected.Keys.ToArray())appendSelected[k]=false;RefreshAppendRows();}),Button("勾选筛选结果",()=>{foreach(var k in appendSelected.Keys.Where(k=>k.Contains(appendSearch.Text??"",StringComparison.OrdinalIgnoreCase)).ToArray())appendSelected[k]=true;RefreshAppendRows();})),
   appendSearch,appendScroll,appendAudio,appendCompile,
   Button("追加 / 覆盖勾选动画",()=>_=Run(AppendSelectedAnimations),true),
   Text("Blender 覆盖动作沿用原去根运动轴，新动作保留源根运动；CS2 覆盖动作沿用原 ModelDoc 设置，新动作使用转换页根运动选项。音频选项关闭时保留已有声音事件，但不为新动作生成音频。",12,"#93A9BC"))));RefreshAppendRows();
 }
 async Task LoadAppendActions()
 {
  var package=Path.GetFullPath(Value("append_package"));var pkg=JsonNode.Parse(File.ReadAllText(Path.Combine(package,"package.json")))!;
  var root=Value("game");var anim=pkg["animationSource"]!.ToString();
  if(!File.Exists(Path.Combine(root,"chr",anim+".anibnd.dcx")))root=Path.Combine(package,"source_native");
  var output=Path.Combine(activeTaskCache??Value("cache"),"append_list.json");string[] names;
  if(File.Exists(Path.Combine(root,"chr",anim+".anibnd.dcx")))
  {await Exec(Worker(),"actions","--root",root,"--character",pkg["character"]!.ToString(),"--animation",anim,"--out",output);names=JsonNode.Parse(File.ReadAllText(output))!["actions"]!.AsArray().Select(x=>x!["name"]!.ToString()).ToArray();}
  else {names=pkg["clips"]!.AsArray().Select(x=>x!["name"]!.ToString()).ToArray();Log("未找到原始动画包，仅列出已有采样动作；新增未采样动作请设置游戏解包目录。");}
  appendExisting.Clear();
  if(appendTarget.SelectedIndex==0)
  {await BlenderScript("blend_list_actions.py",Value("append_blend"),output);foreach(var x in JsonNode.Parse(File.ReadAllText(output))!["actions"]!.AsArray())appendExisting.Add(x!.ToString());}
  else
  {var path=Path.Combine(Value("append_addon"),"rawmodels/sekiro/characters",Value("append_name"),"compile_export.json");foreach(var x in JsonNode.Parse(File.ReadAllText(path))!["actions"]!.AsArray())appendExisting.Add(x!["source"]!.ToString());}
  appendSelected.Clear();foreach(var name in names.Order())appendSelected[name]=false;appendContext=AppendContext();RefreshAppendRows();Log($"可选 {names.Length} 个动作；已有 {appendExisting.Count} 个。默认不勾选，避免误覆盖。");
 }
 async Task AppendSelectedAnimations()
 {
  if(appendContext!=AppendContext())throw new Exception("目标路径已改变，请重新加载可追加动作");
  var selected=appendSelected.Where(x=>x.Value).Select(x=>x.Key).ToArray();if(selected.Length==0)throw new Exception("请选择新增或覆盖的动作");
  var cache=activeTaskCache??Value("cache");var file=Path.Combine(cache,"append_selected.json");File.WriteAllText(file,JsonSerializer.Serialize(selected));
  var a=new List<string>{"--package",Value("append_package"),"--clips",file,"--worker",Worker(),"--game",Value("game"),"--blender",Value("blender"),"--cache",cache};
  if(appendTarget.SelectedIndex==0)a.AddRange(new[]{"--blend",Value("append_blend")});
  else
  {a.AddRange(new[]{"--addon",Value("append_addon"),"--name",Value("append_name"),"--motion-axes",Cs2Axes(),"--dsas",Value("dsas"),"--ffmpeg",Value("ffmpeg")});if(appendAudio.IsChecked==true)a.Add("--audio");if(appendCompile.IsChecked==true)a.Add("--compile");}
  await Python("append_animations.py",a.ToArray());foreach(var n in selected)appendExisting.Add(n);RefreshAppendRows();status.Text=$"追加 / 覆盖完成：{selected.Length} 个动作；其他动作保留，请重新打开文件";
 }
}
