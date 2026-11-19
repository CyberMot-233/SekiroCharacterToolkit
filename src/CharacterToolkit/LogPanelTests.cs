using Avalonia;
using Avalonia.Controls;
using Avalonia.Media;
using Avalonia.Media.Imaging;
using Avalonia.VisualTree;
namespace SekiroCharacterToolkit;
public partial class MainWindow
{
 async Task<object> TestLogPanel(string report)
 {
  ShowCs2();var oldLog=runLog;var oldWidth=Width;var oldHeight=Height;
  runLog=Path.ChangeExtension(report,"synthetic.log");File.WriteAllText(runLog,"");logs.Text="";
  var longPath=Path.Combine(home,string.Concat(Enumerable.Repeat("导出测试目录_",24)),"reports","compiled_verify.log");
  Log("LOG_BEGIN · 完整日志标记");
  for(int n=0;n<400;n++)Log($"[{n:D3}] 动作 c7400_a000_003018 / Katana 第 84 帧 · 位置回读检查\n报告：{longPath}");
  SetFailure(new InvalidOperationException("测试错误：动作 c7400_a000_003018 / Katana 第 84 帧；完整日志："+longPath));
  await Task.Delay(350);
  var checks=new List<object>();
  foreach(var size in new[]{(1180d,760d),(1440d,920d)})
  {
   Width=size.Item1;Height=size.Item2;await Task.Delay(350);UpdateLayout();
   var point=logs.TranslatePoint(new Point(),this)??throw new Exception("Log is detached");
   var scroll=logs.GetVisualDescendants().OfType<ScrollViewer>().FirstOrDefault()??throw new Exception("Log ScrollViewer missing");
   var debugBitmap=new RenderTargetBitmap(new PixelSize((int)Bounds.Width,(int)Bounds.Height));debugBitmap.Render(this);debugBitmap.Save(Path.ChangeExtension(report,"debug.png"));
   if(point.Y+logs.Bounds.Height>Bounds.Height+1||logs.Bounds.Height<90)throw new Exception($"Log exceeds window bounds: y={point.Y}, h={logs.Bounds.Height}, window={Bounds}, footer={logFooter?.Bounds}");
   if(logs.TextWrapping!=TextWrapping.Wrap||scroll.Offset.X>1||scroll.Extent.Width>scroll.Viewport.Width+1)throw new Exception("Log horizontal overflow");
   if(status.Bounds.Height>32||ToolTip.GetTip(status)==null)throw new Exception("Status overflow or missing details");
   checks.Add(new{width=Bounds.Width,height=Bounds.Height,logY=point.Y,logHeight=logs.Bounds.Height,horizontalOffset=scroll.Offset.X,statusHeight=status.Bounds.Height});
   var bitmap=new RenderTargetBitmap(new PixelSize((int)Bounds.Width,(int)Bounds.Height));bitmap.Render(this);
   bitmap.Save(Path.ChangeExtension(report,$"log-{(int)size.Item1}.png"));
  }
  followLog.IsChecked=false;logs.CaretIndex=8;var caret=logs.CaretIndex;
  Log("FOLLOW_DISABLED_MARKER");await Task.Delay(150);
  if(logs.CaretIndex!=caret)throw new Exception("Log follow-off moved caret");
  followLog.IsChecked=true;Log("FOLLOW_ENABLED_MARKER");await Task.Delay(150);
  if(logs.CaretIndex!=logs.Text?.Length)throw new Exception("Log follow-on did not reach end");
  if(!File.ReadAllText(runLog).Contains("LOG_BEGIN")||logs.Text!.Contains("LOG_BEGIN"))throw new Exception($"Full log / visible tail retention failed: file={runLog}, disk={File.ReadAllText(runLog).Contains("LOG_BEGIN")}, visible={logs.Text!.Contains("LOG_BEGIN")}, length={logs.Text!.Length}, first={logs.Text![..Math.Min(80,logs.Text.Length)]}");
  runLog=oldLog;Width=oldWidth;Height=oldHeight;failureDetail=null;ToolTip.SetTip(status,null);status.Text="日志面板测试通过";
  return new{passed=true,checks,followToggle=true,fullDiskLog=true};
 }
}
