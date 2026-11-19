using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Primitives;
using Avalonia.Layout;
using Avalonia.Media;
using Avalonia.Threading;
using Avalonia.VisualTree;
namespace SekiroCharacterToolkit;
public partial class MainWindow
{
 readonly CheckBox followLog=new(){Content="跟随最新",IsChecked=true,VerticalAlignment=VerticalAlignment.Center};
 Grid? logFooter;
 string? failureDetail;
 bool logScrollQueued;
 readonly object logFileLock=new();
 readonly System.Collections.Concurrent.ConcurrentQueue<string> pendingLogs=new();
 int logFlushQueued;
 void AppendLog(string text)
 {
  var file=runLog;
  try{if(file!=null)lock(logFileLock)File.AppendAllText(file,text+Environment.NewLine);}catch{}
  pendingLogs.Enqueue(text);
  if(Interlocked.Exchange(ref logFlushQueued,1)==0)Dispatcher.UIThread.Post(FlushLogs);
 }
 void FlushLogs()
 {
  Interlocked.Exchange(ref logFlushQueued,0);
  var buffer=new System.Text.StringBuilder(logs.Text);
  while(pendingLogs.TryDequeue(out var line))buffer.Append('\n').Append(line);
  var next=buffer.ToString();logs.Text=next.Length>70000?next[^60000..]:next;
  if(followLog.IsChecked==true)FollowLatestLog();
 }
 void FollowLatestLog()
 {
  logs.CaretIndex=logs.Text?.Length??0;
  if(logScrollQueued)return;logScrollQueued=true;
  Dispatcher.UIThread.Post(()=>{
   logScrollQueued=false;if(followLog.IsChecked!=true)return;
   logs.UpdateLayout();
   var scroll=logs.GetVisualDescendants().OfType<ScrollViewer>().FirstOrDefault();
   if(scroll!=null){scroll.ScrollToEnd();scroll.Offset=new Vector(0,scroll.Offset.Y);}
  },DispatcherPriority.Background);
 }
 Control BuildLogPanel()
 {
  logs.TextWrapping=TextWrapping.Wrap;logs.FontSize=13;logs.MinHeight=90;
  logs.HorizontalAlignment=HorizontalAlignment.Stretch;logs.VerticalAlignment=VerticalAlignment.Stretch;
  ScrollViewer.SetHorizontalScrollBarVisibility(logs,ScrollBarVisibility.Disabled);
  ScrollViewer.SetVerticalScrollBarVisibility(logs,ScrollBarVisibility.Auto);
  status.TextWrapping=TextWrapping.NoWrap;status.TextTrimming=TextTrimming.CharacterEllipsis;
  status.VerticalAlignment=VerticalAlignment.Center;
  var top=new Grid{ColumnDefinitions=new ColumnDefinitions("*,Auto"),Margin=new Thickness(0,0,0,6)};
  top.Children.Add(status);
  var actions=Row(Button("取消任务",()=>cancel?.Cancel()),Button("打开输出",()=>Open(lastJob??Value("output"))),Button("打开模型",OpenBlend));
  Grid.SetColumn(actions,1);top.Children.Add(actions);status.Margin=new Thickness(0,0,12,0);
  var bar=new Grid{ColumnDefinitions=new ColumnDefinitions("*,Auto"),Margin=new Thickness(0,5,0,5)};
  bar.Children.Add(Text("任务日志",13,"#93A9BC"));
  var buttons=Row(followLog,AsyncButton("复制完整日志",CopyLog),Button("打开日志文件",OpenLog));
  Grid.SetColumn(buttons,1);bar.Children.Add(buttons);
  followLog.IsCheckedChanged+=(_,_)=>{if(followLog.IsChecked==true)FollowLatestLog();};
  logs.SizeChanged+=(_,_)=>{if(followLog.IsChecked==true)FollowLatestLog();};
  logFooter=new Grid{RowDefinitions=new RowDefinitions("Auto,3,Auto,*")};
  logFooter.Children.Add(top);Grid.SetRow(progress,1);logFooter.Children.Add(progress);
  Grid.SetRow(bar,2);logFooter.Children.Add(bar);Grid.SetRow(logs,3);logFooter.Children.Add(logs);
  return logFooter;
 }
 void SetFailure(Exception error)
 {
  failureDetail=error.ToString();
  var first=error.Message.Split(new[]{'\r','\n'},StringSplitOptions.RemoveEmptyEntries).FirstOrDefault()??error.Message;
  var suffix=first.IndexOf("；完整日志：",StringComparison.Ordinal);
  if(suffix>=0)first=first[..suffix];
  status.Text="失败："+first;ToolTip.SetTip(status,failureDetail);Log(failureDetail);
 }
 async Task CopyLog()
 {
  // The visible tail is capped; the file retains all output from this task.
  string content;lock(logFileLock)content=runLog!=null&&File.Exists(runLog)?File.ReadAllText(runLog):logs.Text??failureDetail??"暂无日志";
  if(Clipboard is {} clipboard)await clipboard.SetTextAsync(content);
 }
 void OpenLog()
 {
  if(runLog!=null&&File.Exists(runLog))Open(runLog);
  else{var dir=Path.Combine(Value("cache"),"logs");Directory.CreateDirectory(dir);Open(dir);}
 }
}
