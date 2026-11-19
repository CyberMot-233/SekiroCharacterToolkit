using System.Text.Json;
using System.Text.Json.Nodes;
using Avalonia.Controls;
namespace SekiroCharacterToolkit;
public partial class MainWindow
{
 readonly ComboBox blendOutputMode=new(){Width=490,ItemsSource=new[]{"分批生成多个完整 Blender 工程（低内存）","全部动作生成一个完整 Blender 工程（高内存）"},SelectedIndex=0};
 bool UseBatches=>blendOutputMode.SelectedIndex==0;
 readonly CheckBox actionDiskCache=new(){Content="动作先写本地缓存并释放内存，全部完成再汇总成品",IsChecked=true};
 readonly CheckBox autoClearCache=new(){Content="成功并验证后自动删除本次动作 / 临时缓存（失败保留续跑）",IsChecked=true};
 readonly TextBox batchSize=new(){Text="8",Width=80};
 void InitMemory(Dictionary<string,string>? saved)
 {npcWeaponMode.SelectedIndex=saved?.GetValueOrDefault("npc_weapon_mode","auto")=="fixed"?1:0;actionDiskCache.IsChecked=saved?.GetValueOrDefault("action_disk_cache","true")!="false";autoClearCache.IsChecked=saved?.GetValueOrDefault("auto_clear_cache","true")!="false";blendOutputMode.SelectedIndex=saved?.GetValueOrDefault("blend_output_mode",saved?.GetValueOrDefault("batch_build","true")=="false"?"single":"batches")=="single"?1:0;batchSize.Text=saved?.GetValueOrDefault("batch_size","8")??"8";batchSize.IsEnabled=UseBatches;blendOutputMode.SelectionChanged+=(_,_)=>batchSize.IsEnabled=UseBatches;}
 async Task BuildPackage(string job,bool resume=false)
 {
  int size=8;if(UseBatches&&(!int.TryParse(batchSize.Text,out size)||size<1||size>128))throw new Exception("每批动作数需为 1–128；内存紧张时建议 1–8");
  SetNpcWeaponMode(job);var pkg=JsonNode.Parse(File.ReadAllText(Path.Combine(job,"package.json")))!;
  if(pkg["textures"]!.AsObject().Any(x=>!File.Exists(Path.Combine(job,"_internal","rgba",x.Key+".tif"))))await Python("prepare_textures.py",job);
  if(blender.IsChecked!=true&&!resume)return;
  var argv=new List<string>{job,"--blender",Value("blender"),"--batch-size",UseBatches?size.ToString():"0","--helper-visibility",HelperVisibility()};
  argv.AddRange(new[]{"--cache-root",Value("cache")});if(actionDiskCache.IsChecked==true)argv.Add("--action-cache");if(autoClearCache.IsChecked!=true)argv.Add("--keep-action-cache");
  if(cleanBones.IsChecked==true)argv.Add("--clean-bones");if(restoreHierarchy.IsChecked==true)argv.Add("--hierarchy");
  var options=Path.Combine(job,"root_motion_options.json");
  if(!resume&&clipSource!=null&&characters.SelectedItem is string&&clipSource==CurrentClipSource())
  {
   var available=pkg["clips"]!.AsArray().Select(c=>c!["name"]!.ToString()).ToHashSet();
   var names=clipChoices.Where(c=>c.InPlace&&available.Contains(c.Name)).Select(c=>c.Name).ToArray();
   if(names.Length>0){if(RootAxes().Length==0)throw new Exception("请选择去根运动轴");File.WriteAllText(options,JsonSerializer.Serialize(new{actions=names,axes=RootAxes()}));}
  }
  if(File.Exists(options))argv.AddRange(new[]{"--root-options",options});
  Log(UseBatches?$"输出方式：每批 {size} 个动作 → 多个完整工程":"输出方式：全部所选动作 → 一个完整工程；从原生数据统一重建，不拼接不同批次骨架。");
  Log("直接导出：生成时完成骨骼清理、层级、武器、去根运动和 AFF 设置，每个工程仅保存一次；随后只读验证。");
  await Python("build_pipeline.py",argv.ToArray());
 }
 async Task ResumePackage()
 {
  var job=await PickExisting();await BuildPackage(job,true);lastJob=job;Summarize(job);
  Log(UseBatches?"分批构建完成；原生包未重新提取。分批工程见 animation_batches，音频可单独补跑。":"单工程构建完成；所有所选动作在同一个角色 blend 内，旧分批文件保留。音频可单独补跑。");
 }
 string? BatchBlend(string job)
 {
  var index=Path.Combine(job,"blend_batches.json");if(!File.Exists(index))return null;
  var data=JsonNode.Parse(File.ReadAllText(index));
  return data?["batches"]?.AsArray().FirstOrDefault(b=>b?["passed"]?.GetValue<bool>()==true)?["blend"]?.GetValue<string>();
 }
}
