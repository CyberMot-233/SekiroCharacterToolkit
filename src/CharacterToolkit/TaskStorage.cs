using System.Text.Json;
namespace SekiroCharacterToolkit;
public partial class MainWindow
{
 string? activeTaskCache;
 bool taskReportsPassed=true;
 void BeginTaskStorage()
 {
  taskReportsPassed=true;LocalStorage.ApplyCurrent(Value("cache"));
  activeTaskCache=Path.Combine(Path.GetFullPath(Value("cache")),"tasks",DateTime.Now.ToString("yyyyMMdd_HHmmss_fff")+"_"+Guid.NewGuid().ToString("N"));
  Directory.CreateDirectory(activeTaskCache);File.WriteAllText(Path.Combine(activeTaskCache,".sct-task"),"owned-task-cache-v1");
  Log("本次临时缓存："+activeTaskCache);
 }
 void FinishTaskStorage(bool success)
 {
  var target=activeTaskCache;activeTaskCache=null;
  if(target==null)return;
  if(!success||!taskReportsPassed||autoClearCache.IsChecked!=true){Log("本次缓存保留："+target);return;}
  try
  {
   var root=Path.GetFullPath(Path.Combine(Value("cache"),"tasks"))+Path.DirectorySeparatorChar;
   var full=Path.GetFullPath(target);
   if(!full.StartsWith(root,StringComparison.OrdinalIgnoreCase)||!File.Exists(Path.Combine(full,".sct-task")))throw new IOException("拒绝清理非本次缓存目录");
   void DeleteTree(string dir)
   {
    if((File.GetAttributes(dir)&FileAttributes.ReparsePoint)!=0)throw new IOException("缓存目录包含链接，保留人工检查："+dir);
    foreach(var f in Directory.EnumerateFiles(dir)){if((File.GetAttributes(f)&FileAttributes.ReparsePoint)!=0)throw new IOException("缓存文件包含链接："+f);File.Delete(f);}
    foreach(var d in Directory.EnumerateDirectories(dir))DeleteTree(d);
    Directory.Delete(dir);
   }
   DeleteTree(full);Log("已自动清理本次临时缓存；配置、日志、其他任务及成品保留。");
  }catch(Exception e){Log("缓存未完全清理（成品不受影响）："+e.Message);}
 }
 async Task CheckStorage()
 {
  var report=Cache("storage_report.json");
  await Python("storage_probe.py","--output",report,"--blender",Value("blender"));
  var result=JsonDocument.Parse(File.ReadAllText(report));
  if(!result.RootElement.GetProperty("passed").GetBoolean())throw new Exception("实际缓存路径检测失败："+report);
  Log("实际缓存路径通过，报告："+report+"；Windows 分页文件由系统管理。");
 }
 object TestStorageLifecycle()
 {
  var old=autoClearCache.IsChecked;autoClearCache.IsChecked=true;
  BeginTaskStorage();var failed=activeTaskCache!;File.WriteAllText(Path.Combine(failed,"test.dat"),"keep on failure");FinishTaskStorage(false);
  bool failureKept=Directory.Exists(failed);
  BeginTaskStorage();var success=activeTaskCache!;File.WriteAllText(Path.Combine(success,"test.dat"),"delete on success");FinishTaskStorage(true);
  bool successCleaned=!Directory.Exists(success),unrelatedKept=Directory.Exists(failed);
  // This is our synthetic failed-task directory, not a real failed job.
  activeTaskCache=failed;FinishTaskStorage(true);autoClearCache.IsChecked=old;
  if(!failureKept||!successCleaned||!unrelatedKept)throw new Exception("Task cache lifecycle regression");
  return new {failureKept,successCleaned,unrelatedKept};
 }
}
