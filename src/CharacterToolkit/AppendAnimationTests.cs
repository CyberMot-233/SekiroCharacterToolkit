using Avalonia.Controls;
namespace SekiroCharacterToolkit;
public partial class MainWindow
{
 object TestAppendControls()
 {
  appendSelected.Clear();appendExisting.Clear();appendSearch.Text="";
  appendSelected["c7400/a000_001040"]=false;appendSelected["c7400/a000_003012"]=false;appendExisting.Add("c7400/a000_001040");
  ShowAppendAnimations();
  var rows=appendRows.Children.OfType<CheckBox>().ToArray();
  if(rows.Length!=2||!rows[0].Content!.ToString()!.Contains("覆盖")||!rows[1].Content!.ToString()!.Contains("新增"))throw new Exception("Append status labels incorrect");
  rows[1].IsChecked=true;appendSearch.Text="001040";RefreshAppendRows();
  if(appendRows.Children.Count!=1||!appendSelected["c7400/a000_003012"])throw new Exception($"Filter lost append selection: rows={appendRows.Children.Count}, selected={appendSelected["c7400/a000_003012"]}, search={appendSearch.Text}");
  var before=AppendContext();appendTarget.SelectedIndex=1-appendTarget.SelectedIndex;
  if(before==AppendContext())throw new Exception("Target switch did not invalidate selection context");
  ShowSettings();ShowAppendAnimations();appendSearch.Text="";
  if(!appendSelected["c7400/a000_003012"])throw new Exception("Navigation lost append selection");
  appendSelected.Clear();appendExisting.Clear();RefreshAppendRows();
  return new{passed=true,existingAndNewLabels=true,filterRetainsSelection=true,targetContextGuard=true,navigationPreservesSelection=true};
 }
}
