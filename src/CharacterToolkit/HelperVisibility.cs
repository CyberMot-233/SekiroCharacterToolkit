using Avalonia.Controls;
namespace SekiroCharacterToolkit;
public partial class MainWindow
{
 readonly CheckBox showHelpers=new(){Content="显示 AFF 辅助骨（可选择，保留原动作）",IsChecked=true};
 string HelperVisibility()=>showHelpers.IsChecked==true?"visible":"hidden";
 async Task ApplyHelperVisibility(string job,bool backup=false)=>await BlenderScript("helper_visibility.py",backup?new[]{job,"--visibility",HelperVisibility()}:new[]{job,"--visibility",HelperVisibility(),"--no-backup"});
 async Task ExistingHelperVisibility(){var job=await PickExisting();await ApplyHelperVisibility(job,true);Summarize(job);Log("AFF 显示状态已应用；重新打开磁盘工程。动画、层级、权重未改变。");}
}
