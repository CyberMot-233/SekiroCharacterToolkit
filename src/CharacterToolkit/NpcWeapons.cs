using System.Text.Json.Nodes;
using Avalonia.Controls;
namespace SekiroCharacterToolkit;
public partial class MainWindow
{
 readonly ComboBox npcWeaponMode=new(){Width=540,ItemsSource=new[]{"内置武器：自动匹配动作（推荐）","内置武器：固定 NPC 外观参数"},SelectedIndex=0};
 string NpcWeaponMode=>npcWeaponMode.SelectedIndex==1?"fixed":"auto";
 void SetNpcWeaponMode(string job)
 {
  var file=Path.Combine(job,"package.json");var pkg=JsonNode.Parse(File.ReadAllText(file))!;
  if(pkg["npcAppearance"] is not JsonObject appearance)return;
  appearance["weapon_policy"]=NpcWeaponMode;
  File.WriteAllText(file,pkg.ToJsonString());
 }
 async Task RepairNpcWeapons()
 {
  var job=await PickExisting();
  await Exec(Value("blender"),"--background","--factory-startup","--disable-autoexec","--threads","4","--python-exit-code","1","--python",Path.Combine(home,"scripts","repair_npc_weapons.py"),"--",job,"--mode",NpcWeaponMode);
  status.Text="武器状态修复完成；原工程已备份，动作变换与模型未重烘";
  Log(status.Text+" → "+job);
 }
}
