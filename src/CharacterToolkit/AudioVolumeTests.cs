using System.Text.Json;
using Avalonia.Controls;
using Avalonia.LogicalTree;
namespace SekiroCharacterToolkit;
public partial class MainWindow
{
 object TestAudioVolumeControls()
 {
  var priorPackage=Value("cs2_package");var priorName=Value("cs2_name");
  fields["cs2_package"].Text="audio-volume-ui-test";fields["cs2_name"].Text="audio_volume_test";
  BeginVolumeList();cs2Selected.Clear();cs2Selected["c0000/a000_000001"]=true;cs2Selected["c0000/a000_000002"]=false;
  cs2BatchVolume.Value=5;SetSelectedAudioVolume();
  if(Volumes().GetValueOrDefault("c0000/a000_000001")!=5||Volumes().ContainsKey("c0000/a000_000002"))throw new Exception("Batch volume changed an unselected animation");
  ShowCs2();var entry=cs2Clips.Children[0].GetLogicalDescendants().OfType<NumericUpDown>().Single();entry.Value=2.5m;
  if(Volumes()["c0000/a000_000001"]!=2.5m)throw new Exception("Per-animation volume not stored");
  ShowSettings();ShowCs2();
  if(cs2Clips.Children[0].GetLogicalDescendants().OfType<NumericUpDown>().Single().Value!=2.5m)throw new Exception("Volume lost after navigation");
  var saved=new Dictionary<string,string?>();SaveCs2(saved);var decoded=JsonSerializer.Deserialize<Dictionary<string,Dictionary<string,decimal>>>(saved["cs2_volume_profiles"]!)!;
  if(decoded[VolumeScope()]["c0000/a000_000001"]!=2.5m)throw new Exception("Volume persistence failed");
  fields["cs2_name"].Text="another_model";if(Volumes().Count!=0)throw new Exception("Volume leaked into another model");
  bool guard=false;try{RequireVolumeContext();}catch{guard=true;}if(!guard)throw new Exception("Stale selection guard failed");
  cs2Selected.Clear();fields["cs2_package"].Text=priorPackage;fields["cs2_name"].Text=priorName;BeginVolumeList();RefreshCs2Clips();
  return new{passed=true,independent=true,batchSelectedOnly=true,persistence=true,scopeIsolation=true,staleContextGuard=true};
 }
}
