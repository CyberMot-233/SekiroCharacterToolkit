using System.Text.Json;
using System.Text.Json.Nodes;
using Avalonia.Controls;
using Avalonia.Layout;
namespace SekiroCharacterToolkit;

public partial class MainWindow
{
 sealed class ClipChoice
 {
  public string Name {get;init;}="";
  public bool Export {get;set;}=true;
  public bool InPlace {get;set;}
  public bool Auxiliary {get;init;}
 }
 readonly List<ClipChoice> clipChoices=new();
 readonly ListBox clipList=new(){Height=210,Background=Brush("#09121E")};
 readonly TextBox clipSearch=new(){Watermark="搜索动作 ID / 包名，例如 a000_003022"};
 readonly TextBlock clipCount=new();
 readonly CheckBox rootX=new(){Content="X 位移",IsChecked=true},rootY=new(){Content="Y 位移",IsChecked=true},rootZ=new(){Content="Z 位移（高度）",IsChecked=false};
 readonly CheckBox cleanBones=new(){Content="清理未使用骨骼（保留蒙皮、挂点及必要辅助骨）",IsChecked=true};
 readonly CheckBox restoreHierarchy=new(){Content="直接生成源骨骼层级与名称（无需导出后重烘）",IsChecked=true};
 string? clipSource,existingActionJob;
 readonly ComboBox trimAction=new(){Width=330,PlaceholderText="读取已有工程后选择动作"};
 readonly TextBox trimEnd=new(){Width=95,Watermark="例如 198"};
 string CurrentClipSource()=>Selected()+"|"+(animation.SelectedItem as string??Selected());
 void UpdateClipCount()=>clipCount.Text=$"动作 {clipChoices.Count} · 导出 {clipChoices.Count(c=>c.Export)} · 去根运动 {clipChoices.Count(c=>c.InPlace)}";
 void RenderClipList()
 {
  string query=clipSearch.Text?.Trim()??"";
  clipList.ItemsSource=clipChoices.Where(c=>c.Name.Contains(query,StringComparison.OrdinalIgnoreCase)).Select(c=>
  {
   var export=new CheckBox{Content="导出",IsChecked=c.Export,Width=72};
   var inplace=new CheckBox{Content="去根运动",IsChecked=c.InPlace,Width=116};
   export.IsCheckedChanged+=(_,_)=>{c.Export=export.IsChecked==true;UpdateClipCount();};
   inplace.IsCheckedChanged+=(_,_)=>{c.InPlace=inplace.IsChecked==true;UpdateClipCount();};
   return Row(export,inplace,Text(c.Name+(c.Auxiliary?"  [脸部辅助源]":""),12));
  }).ToArray();
  UpdateClipCount();
 }
 void MarkClips(bool root,bool value,bool filtered=false)
 {
  foreach(var c in clipChoices.Where(c=>!filtered||c.Name.Contains(clipSearch.Text??"",StringComparison.OrdinalIgnoreCase)))
   if(root)c.InPlace=value;else c.Export=value;
  RenderClipList();
 }
 void ShowActions()
 {
  Show(Card(Stack(Text("动作选择 / 分轴去根运动",24),Text("动作显示游戏原始 HKX ID，不猜测中文名称。导出勾选和去根运动勾选相互独立。",12,"#93A9BC"),
   Row(Button("加载当前角色动作",()=>_=Run(LoadClips)),Button("读取已有工程动作",()=>_=Run(LoadExistingClips))),
   clipSearch,Row(Button("全选导出",()=>MarkClips(false,true)),Button("清空导出",()=>MarkClips(false,false)),Button("勾选搜索结果",()=>MarkClips(false,true,true))),
   clipCount,clipList,Row(Button("全部去根运动",()=>MarkClips(true,true)),Button("清空去根运动",()=>MarkClips(true,false)),Button("搜索结果去根运动",()=>MarkClips(true,true,true))),
   Row(Text("去除轴（Blender 坐标）"),rootX,rootY,rootZ),
   Text("所选位移轴固定在动作起始值；未选轴、根旋转和身体动作保留。X/Y 为水平，Z 为高度；不删除 Root 骨，也不修改源 HKX。",12,"#93A9BC"),
   Row(Button("导出勾选动作",()=>_=Run(ExportCharacter),true),Button("一键导出全部动作",()=>_=Run(()=>ExportCharacterSelected(true))),Button("处理已有工程的勾选动作",()=>_=Run(ProcessExistingRoot))),
   Text("新导出包含角色、所选 Actions、贴图及勾选的音频。已有工程处理会先备份；只处理“去根运动”列勾选的动作，不删除其他动作。",12,"#93A9BC"),
   Text("动作末尾修复 / 完整通道裁剪",19),
   Button("修复旧工程末帧（从源重建新副本）",()=>_=Run(RepairAnimationEndpoints)),
   Text("重建保留动作列表和去根运动轴，不继承手工姿态修改；原任务不覆盖。新导出已自动修正压缩块末帧采样。",12,"#93A9BC"),
   Row(trimAction,Text("保留至 Blender 帧"),trimEnd),
   Button("裁剪所选动作尾部（含隐藏辅助骨）",()=>_=Run(TrimExistingAction)),
   Text("先读取已有工程动作。裁剪覆盖所选 Action 的全部通道：身体、隐藏 AFF、根运动、装备和显隐；保留切点姿势并停止在该姿势，先备份。不是只删除可见骨骼的关键帧。",12,"#93A9BC"))));
  RenderClipList();
 }
 async Task LoadClips()
 {
  var source=CurrentClipSource();
  await Exec(Worker(),"actions","--root",Value("game"),"--character",Selected(),"--animation",animation.SelectedItem as string??Selected(),"--out",Cache("actions.json"));
  var rows=JsonNode.Parse(File.ReadAllText(Cache("actions.json")))!["actions"]!.AsArray();
  clipChoices.Clear();
  clipChoices.AddRange(rows.Select(r=>new ClipChoice{Name=r!["name"]!.ToString(),Auxiliary=r["auxiliary"]?.GetValue<bool>()==true}).OrderBy(c=>c.Name));
  clipSource=source;existingActionJob=null;RenderClipList();Log($"加载 {clipChoices.Count} 个动作");
 }
 async Task LoadExistingClips()
 {
  var job=await PickExisting();var pkg=JsonNode.Parse(File.ReadAllText(Path.Combine(job,"package.json")))!;
  clipChoices.Clear();clipChoices.AddRange(pkg["clips"]!.AsArray().Select(c=>new ClipChoice{Name=c!["name"]!.ToString()}).OrderBy(c=>c.Name));
  clipSource=null;existingActionJob=job;trimAction.ItemsSource=clipChoices.Select(c=>c.Name).ToArray();trimAction.SelectedIndex=0;RenderClipList();Log("已有工程："+job);
 }
 string RootAxes()=>string.Concat(rootX.IsChecked==true?"X":"",rootY.IsChecked==true?"Y":"",rootZ.IsChecked==true?"Z":"");
 async Task ApplyRoot(string job,bool backup)
 {
  var available=JsonNode.Parse(File.ReadAllText(Path.Combine(job,"package.json")))!["clips"]!.AsArray().Select(c=>c!["name"]!.ToString()).ToHashSet();
  var selected=clipChoices.Where(c=>c.InPlace&&available.Contains(c.Name)).Select(c=>c.Name).ToArray();
  if(selected.Length==0)return;
  if(RootAxes().Length==0)throw new Exception("请勾选要去除位移的 X / Y / Z 轴");
  var opts=Path.Combine(job,"root_motion_options.json");File.WriteAllText(opts,JsonSerializer.Serialize(new{actions=selected,axes=RootAxes()}));
  await BlenderScript("root_motion.py",backup?new[]{job,"--options",opts}:new[]{job,"--options",opts,"--no-backup"});
 }
 async Task ProcessExistingRoot()
 {
  if(existingActionJob==null)throw new Exception("先点击“读取已有工程动作”，再勾选去根运动的动作");
  if(!clipChoices.Any(c=>c.InPlace))throw new Exception("请在“去根运动”列勾选动作");
  await ApplyRoot(existingActionJob,true);await BlenderScript("verify_saved.py",existingActionJob);Summarize(existingActionJob);
 }
 async Task BlenderScript(string script,params string[] argv)=>await Exec(Value("blender"),new[]{"--background","--factory-startup","--disable-autoexec","--threads","4","--python-exit-code","1","--python",Path.Combine(home,"scripts",script),"--"}.Concat(argv).ToArray());
 async Task RepairAnimationEndpoints(){var job=await PickExisting();var dest=job+"_endfix_"+DateTime.Now.ToString("yyyyMMdd_HHmmss_fff");await Python("repair_animation_endpoints.py",job,"--worker",Worker(),"--blender",Value("blender"),"--out",dest,"--helper-visibility",HelperVisibility());lastJob=dest;Summarize(dest);Log("末帧修复新副本："+dest);}
 async Task TrimExistingAction(){if(existingActionJob==null||trimAction.SelectedItem is not string name)throw new Exception("先读取已有工程并选择要裁剪的动作");if(!double.TryParse(trimEnd.Text,System.Globalization.NumberStyles.Float,System.Globalization.CultureInfo.InvariantCulture,out var end)||!double.IsFinite(end)||end<1)throw new Exception("请输入有效结束帧（支持小数）");await BlenderScript("trim_action.py",existingActionJob,"--action",name,"--end",end.ToString(System.Globalization.CultureInfo.InvariantCulture));await BlenderScript("verify_saved.py",existingActionJob);await BlenderScript("verify_appearance.py",existingActionJob);lastJob=existingActionJob;Summarize(existingActionJob);Log("全部通道已裁剪，请重新打开工程；详情见 action_trim_report.json");}
 async Task RestoreExistingHierarchy(){var job=await PickExisting();await BlenderScript("restore_hierarchy.py",job);await ApplyHelperVisibility(job);await BlenderScript("verify_saved.py",job);await BlenderScript("verify_appearance.py",job);Summarize(job);Log("骨骼层级已修复；重新打开 Blender 文件查看");}
 async Task CleanExistingBones()
 {
  var job=await PickExisting();await BlenderScript("clean_bones.py",job);await ApplyHelperVisibility(job);await BlenderScript("verify_saved.py",job);await BlenderScript("verify_appearance.py",job);Summarize(job);
 }
}

