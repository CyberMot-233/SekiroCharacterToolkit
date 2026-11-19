using Avalonia.Controls;
namespace SekiroCharacterToolkit;
public partial class MainWindow
{
 void ReportUiError(Exception ex)
 {
  SetFailure(ex);
  try{var dir=Path.Combine(Value("cache"),"logs");Directory.CreateDirectory(dir);File.AppendAllText(Path.Combine(dir,"ui_errors.log"),DateTime.Now.ToString("O")+" "+ex+Environment.NewLine);}catch{ /* UI still displays the original error if the chosen disk is unwritable. */ }
 }
 Button AsyncButton(string label,Func<Task> click)
 {
  var button=new Button{Content=label};
  button.Click+=async (_,_)=>{try{await click();}catch(Exception ex){ReportUiError(ex);}};return button;
 }
}
