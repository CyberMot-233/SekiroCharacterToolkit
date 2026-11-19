using System.Text.Json;
using Avalonia.Controls;
using Avalonia.Interactivity;
using Avalonia.LogicalTree;
using Avalonia.VisualTree;
using Avalonia.Media.Imaging;
using Avalonia;
namespace SekiroCharacterToolkit;
public partial class MainWindow
{
 async Task TestNavigation()
 {
  var i=Array.IndexOf(args, "--test-report");
  var report=i>=0?args[i+1]:Path.Combine(home,"tests/navigation_102/result.json");
  Directory.CreateDirectory(Path.GetDirectoryName(report)!);
  await Task.Delay(200);
  int transitions=0;string? error=null;object? storageLifecycle=null;object? logPanel=null;object? audioVolumes=null;object? appendAnimations=null;
  try
  {
   appendAnimations=TestAppendControls();audioVolumes=TestAudioVolumeControls();storageLifecycle=TestStorageLifecycle();ShowCs2();await Task.Delay(100);ShowCs2();await Task.Delay(100);
   fields["cs2_name"].Text="navigation_state";cs2X.IsChecked=false;cs2Z.IsChecked=true;
   cs2Selected["a000_test"]=true;RefreshCs2Clips();
   for(int round=0;round<30;round++)
   {
    foreach(var action in new Action[]{ShowCs2,ShowCharacters,ShowWeapons,ShowExport}){action();transitions++;await Task.Delay(30); }
    if(!page.GetLogicalDescendants().OfType<Button>().Any(b=>Equals(b.Content,"继续已有提取包（无需重新解包）")))throw new Exception("Missing resume button");
    if(!page.GetLogicalDescendants().OfType<Button>().Any(b=>Equals(b.Content,"修复已有工程武器状态（不重烘动作）")))throw new Exception("Missing NPC weapon repair button");
    npcWeaponMode.SelectedIndex=round%2;
    if(NpcWeaponMode!=(round%2==0?"auto":"fixed"))throw new Exception("NPC weapon mode mismatch");
    var jump=page.GetLogicalDescendants().OfType<Button>().Single(b=>Equals(b.Content,"CS2 转换设置 →"));
    jump.RaiseEvent(new RoutedEventArgs(Avalonia.Controls.Button.ClickEvent));transitions++;await Task.Delay(30);
    if(cs2Clips.GetVisualAncestors().All(x=>x!=page))throw new Exception("CS2 page not attached after button click");
    if(!page.GetLogicalDescendants().OfType<Button>().Any(b=>Equals(b.Content,"修复部件显隐（保留材质设置）")))throw new Exception("Missing visibility repair button");
    foreach(var action in new Action[]{ShowActions,ShowSettings,ShowWolf,ShowInfo,ShowCs2,ShowCs2,ShowAppendAnimations}){action();transitions++;await Task.Delay(30); }
    blendOutputMode.SelectedIndex=round%2;if(batchSize.IsEnabled!=UseBatches)throw new Exception("Output mode size enable state mismatch");
    if(Value("cs2_name")!="navigation_state"||cs2X.IsChecked!=false||cs2Z.IsChecked!=true||!cs2Selected["a000_test"])throw new Exception("Form state lost");
    if(npcWeaponMode.SelectedIndex!=round%2)throw new Exception("NPC weapon selection lost");
    await Task.Delay(10);
   }
   if(args.Contains("--test-tools")){await Run(CheckTools);await Run(CheckStorage);if(status.Text!.StartsWith("失败"))throw new Exception(status.Text);}
   if(args.Contains("--test-logs"))logPanel=await TestLogPanel(report);
   await Task.Delay(250);
   if(args.Contains("--test-export-shot")){ShowExport();await Task.Delay(250);}
   var audioArg=Array.IndexOf(args,"--test-audio-addon");
   if(audioArg>=0)
   {
    fields["cs2_addon"].Text=args[audioArg+1];fields["cs2_name"].Text="wolf";fields["cs2_package"].Text="";
    await Run(LoadExistingAudioVolumes);
    if(cs2Selected.Count!=17)throw new Exception("Expected 17 existing audio clips");
    foreach(var key in cs2Selected.Keys.ToArray())cs2Selected[key]=key=="c7400/a000_003013";
    cs2BatchVolume.Value=3;SetSelectedAudioVolume();cs2Compile.IsChecked=true;
    await Run(UpdateAudioVolumes);if(!status.Text!.StartsWith("音量已更新并编译"))throw new Exception(status.Text);
    ShowCs2();await Task.Delay(250);
   }
   var appendArg=Array.IndexOf(args,"--test-append-package");
   if(appendArg>=0)
   {
    fields["append_package"].Text=args[appendArg+1];fields["append_blend"].Text=args[Array.IndexOf(args,"--test-append-blend")+1];appendTarget.SelectedIndex=0;
    await Run(LoadAppendActions);if(appendSelected.Count<=13||appendExisting.Count!=13)throw new Exception("Actual Blender action inventory failed");
    if(appendSelected.Any(x=>x.Value))throw new Exception("Append list selected clips without user choice");
    appendSearch.Text="00301";ShowAppendAnimations();await Task.Delay(250);
   }
   var bitmap=new RenderTargetBitmap(new PixelSize((int)Bounds.Width,(int)Bounds.Height));bitmap.Render(this);bitmap.Save(Path.ChangeExtension(report,"png"));
  }catch(Exception ex){error=ex.ToString();}
  File.WriteAllText(report,JsonSerializer.Serialize(new{passed=error==null,transitions,error,storageLifecycle,logPanel,audioVolumes,appendAnimations,home,cache=Value("cache"),python=Value("python"),tools=args.Contains("--test-tools")?status.Text:null},new JsonSerializerOptions{WriteIndented=true}));
  Environment.ExitCode=error==null?0:1;Close();
 }
}
