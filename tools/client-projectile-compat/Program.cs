using Mono.Cecil;
using Mono.Cecil.Cil;
using System.Security.Cryptography;

if (args.Length == 4 && args[0] == "--repair-market-description") {
    var descInput = Path.GetFullPath(args[1]);
    var descOutput = Path.GetFullPath(args[2]);
    if (File.Exists(descOutput)) throw new InvalidOperationException("output must be new");
    if (Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(descInput))).ToLowerInvariant() !=
        "59867c35054c16247f69902a097fc9b87be90ef9829ab73258d052afce6c22ae")
        throw new InvalidOperationException("expected the audited first shop compatibility DLL");
    var descResolver = new GameAssemblyResolver(Path.GetDirectoryName(descInput)!);
    descResolver.AddSearchDirectory(Path.GetFullPath(args[3]));
    using var descModule = ModuleDefinition.ReadModule(descInput, new ReaderParameters { AssemblyResolver = descResolver });
    var descBefore = Bodies(descModule);
    var descDefinitions = Definitions(descModule);
    var descMethod = Types(descModule.Types).Single(t => t.FullName == "ET.ServerShopPriceCache")
        .Methods.Single(m => m.Name == "ApplyMarketDescriptions");
    var descShape = FlowShape(descMethod);
    var getId = descMethod.Body.Instructions.Single(i => i.Operand is MethodReference m &&
        m.Name == "get_Item" && m.DeclaringType is GenericInstanceType list && list.GenericArguments.Single().FullName == "System.Int32");
    var marketType = Types(descModule.Types).Single(t => t.FullName == "Cal.DataTable.MarketBase");
    var marketItem = marketType.Fields.Single(f => f.Name == "ItemId");
    var getDefinition = Types(descModule.Types).Single(t => t.FullName == "ET.DataTableHelper").Methods.Single(m =>
        m.Name == "Get" && m.GenericParameters.Count == 1 && m.Parameters.Count == 1 && m.Parameters[0].ParameterType.FullName == "System.Int32");
    var getMarket = new GenericInstanceMethod(getDefinition);
    getMarket.GenericArguments.Add(marketType);
    var descIl = descMethod.Body.GetILProcessor();
    var readMarket = Instruction.Create(OpCodes.Call, getMarket);
    var readItem = Instruction.Create(OpCodes.Ldfld, marketItem);
    descIl.InsertAfter(getId, readMarket);
    descIl.InsertAfter(readMarket, readItem);
    descModule.Write(descOutput, new WriterParameters { WriteSymbols = false });
    using var descVerified = ModuleDefinition.ReadModule(descOutput, new ReaderParameters { AssemblyResolver = descResolver });
    var descAfter = Bodies(descVerified);
    if (descDefinitions != Definitions(descVerified) || descModule.Mvid != descVerified.Mvid ||
        !descBefore.Keys.Order().SequenceEqual(descAfter.Keys.Order()) ||
        !descBefore.Keys.Where(k => descBefore[k] != descAfter[k]).SequenceEqual(new[] { descMethod.FullName }))
        throw new InvalidOperationException("changed unrelated definitions or method bodies");
    var verifiedDesc = Types(descVerified.Types).Single(t => t.FullName == "ET.ServerShopPriceCache")
        .Methods.Single(m => m.Name == "ApplyMarketDescriptions");
    var insertedRead = verifiedDesc.Body.Instructions.Single(i => i.Operand is GenericInstanceMethod m && m.Name == "Get" && m.GenericArguments[0].FullName == marketType.FullName);
    var insertedItem = verifiedDesc.Body.Instructions[verifiedDesc.Body.Instructions.IndexOf(insertedRead)+1];
    if (insertedItem.OpCode != OpCodes.Ldfld || ((FieldReference)insertedItem.Operand).FullName != marketItem.FullName)
        throw new InvalidOperationException("unexpected item-ID projection");
    verifiedDesc.Body.Instructions.Remove(insertedRead);
    verifiedDesc.Body.Instructions.Remove(insertedItem);
    if (FlowShape(verifiedDesc) != descShape) throw new InvalidOperationException("changed original description control flow");
    Console.WriteLine("Validated: only two instructions added to project MarketBase configuration ID to ItemId before applying its description");
    Console.WriteLine("Output SHA256: " + Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(descOutput))).ToLowerInvariant());
    return;
}
if (args.Length == 3 && args[0] == "--audit-shop") {
    using var oldShop = ModuleDefinition.ReadModule(args[1]);
    using var newShop = ModuleDefinition.ReadModule(args[2]);
    if (oldShop.Mvid != newShop.Mvid) throw new InvalidOperationException("shop patch changed module identity");
    var oldTypes = Types(oldShop.Types).ToDictionary(t => t.FullName);
    var newTypes = Types(newShop.Types).ToDictionary(t => t.FullName);
    if (oldTypes.Keys.Any(t => !newTypes.ContainsKey(t)) ||
        newTypes.Keys.Except(oldTypes.Keys).Any(t => t != "ET.ServerShopPriceCache"))
        throw new InvalidOperationException("unexpected shop type changes");
    var allowedFields = new HashSet<string> {
        "ET.M2C_GetMarket:PriceList", "ET.M2C_GetMarket:DescriptionList",
        "ET.M2C_SendActiveInfo:ShopPriceData", "ET.M2C_SendActiveInfo:ShopDescriptionData",
        "ET.NetItem:<Description>k__BackingField", "ET.ShopUI:serverRefreshPage"
    };
    foreach (var (name, oldType) in oldTypes) {
        var next = newTypes[name];
        if (oldType.Attributes != next.Attributes || oldType.BaseType?.FullName != next.BaseType?.FullName)
            throw new InvalidOperationException("unexpected existing type modification: " + name);
        foreach (var field in oldType.Fields)
            if (!next.Fields.Any(f => f.FullName == field.FullName && f.Attributes == field.Attributes))
                throw new InvalidOperationException("removed/changed field: " + field.FullName);
        foreach (var field in next.Fields.Where(f => !oldType.Fields.Any(o => o.FullName == f.FullName)))
            if (!allowedFields.Contains(name + ":" + field.Name))
                throw new InvalidOperationException("unexpected new field: " + field.FullName);
    }
    var oldBodies = Bodies(oldShop);
    var newBodies = Bodies(newShop);
    var allowedOwners = new[] {
        "ET.ServerShopPriceCache", "ET.ShopUI", "ET.MultiShopUI", "ET.MarketUI", "ET.TabHelper",
        "ET.M2C_SendActiveInfoHandler", "ET.UpdateBagUIEvent", "ET.UpdateWornEquipUIEvent"
    };
    var methods = Types(newShop.Types).SelectMany(t => t.Methods).ToDictionary(m => m.FullName);
    foreach (var key in oldBodies.Keys)
        if (!newBodies.ContainsKey(key)) throw new InvalidOperationException("removed method: " + key);
    var modified = newBodies.Keys.Where(k => !oldBodies.TryGetValue(k, out var prior) || prior != newBodies[k]).ToArray();
    foreach (var key in modified) {
        var owner = methods[key].DeclaringType.FullName;
        if (!allowedOwners.Any(t => owner == t || owner.StartsWith(t + "/", StringComparison.Ordinal)))
            throw new InvalidOperationException("unrelated shop method changed: " + key);
        Console.WriteLine(key);
    }
    Console.WriteLine($"Shop audit passed: {oldBodies.Count} previous methods retained; {modified.Length} shop-only new/modified bodies; authentication, battle and HUD repair bodies unchanged.");
    return;
}
if (args.Length != 3) throw new ArgumentException("input DLL, new output DLL, original Managed directory required");
var input = Path.GetFullPath(args[0]);
var output = Path.GetFullPath(args[1]);
if (input == output || File.Exists(output)) throw new InvalidOperationException("output must be a new independent file");
if (Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(input))).ToLowerInvariant() !=
    "7d9256fff2746310227e0509eb340198842c78cec7d857e9c482a201e52fc889")
    throw new InvalidOperationException("unsupported client build; inspect it before adapting this repair");
var resolver = new GameAssemblyResolver(Path.GetDirectoryName(input)!);
resolver.AddSearchDirectory(Path.GetFullPath(args[2]));
resolver.AddSearchDirectory(Path.GetDirectoryName(input)!);
using var module = ModuleDefinition.ReadModule(input, new ReaderParameters { AssemblyResolver = resolver });
var before = Bodies(module);
var definitions = Definitions(module);
var playBullet = Types(module.Types).Single(t => t.FullName == "ET.PlayEffectEvent")
    .Methods.Single(m => m.Name == "PlayBulletEffect");
var call = playBullet.Body.Instructions.Single(i => i.OpCode == OpCodes.Call &&
    i.Operand is MethodReference m && m.DeclaringType.FullName == "DG.Tweening.ShortcutExtensions" && m.Name == "DOMove");
var oldReference = (MethodReference)call.Operand;
if (oldReference.ReturnType.FullName != "DG.Tweening.Tweener") throw new InvalidOperationException("unexpected original call signature");
var dependency = resolver.Resolve(module.AssemblyReferences.Single(r => r.Name == "DOTween")).MainModule;
var installed = dependency.GetType("DG.Tweening.ShortcutExtensions").Methods.Single(m =>
    m.Name == "DOMove" && m.Parameters.Select(p => p.ParameterType.FullName).SequenceEqual(new[] {
        "UnityEngine.Transform", "UnityEngine.Vector3", "System.Single", "System.Boolean" }));
if (!installed.ReturnType.FullName.StartsWith("DG.Tweening.Core.TweenerCore`3<", StringComparison.Ordinal))
    throw new InvalidOperationException("unexpected installed DOTween return type");
call.Operand = module.ImportReference(installed);
// MainUI itself invokes this event before the login scene creates MyUnit.
// Match its existing early-return behavior when MainUI is not present.
var head = Types(module.Types).Single(t => t.FullName == "ET.InitHeadInfoEvent").Methods.Single(m => m.Name == "Run");
var originalHeadShape = FlowShape(head);
var originalFirst = head.Body.Instructions[0];
var sceneField = head.Body.Instructions.Select(i => i.Operand).OfType<FieldReference>().First(f => f.Name == "zoneScene");
var componentGetter = head.Body.Instructions.Select(i => i.Operand).OfType<GenericInstanceMethod>()
    .Where(m => m.Name == "GetComponent" && m.GenericArguments[0].FullName == "ET.UnitComponent").DistinctBy(m => m.FullName).Single();
var unitGetter = head.Body.Instructions.Select(i => i.Operand).OfType<MethodReference>().Where(m => m.Name == "get_MyUnit").DistinctBy(m => m.FullName).Single();
var headIl = head.Body.GetILProcessor();
foreach (var guard in new[] {
    Instruction.Create(OpCodes.Ldarg_1), Instruction.Create(OpCodes.Ldfld, sceneField),
    Instruction.Create(OpCodes.Callvirt, componentGetter), Instruction.Create(OpCodes.Callvirt, unitGetter),
    Instruction.Create(OpCodes.Brtrue, originalFirst), Instruction.Create(OpCodes.Ret)
}) headIl.InsertBefore(originalFirst, guard);
Directory.CreateDirectory(Path.GetDirectoryName(output)!);
module.Write(output, new WriterParameters { WriteSymbols = false });
using var verified = ModuleDefinition.ReadModule(output, new ReaderParameters { AssemblyResolver = resolver });
if (module.Mvid != verified.Mvid || definitions != Definitions(verified))
    throw new InvalidOperationException("repair changed module identity or type/member definitions");
var after = Bodies(verified);
if (!before.Keys.Order().SequenceEqual(after.Keys.Order())) throw new InvalidOperationException("method inventory changed");
var changed = before.Keys.Where(key => before[key] != after[key]).ToArray();
if (changed.Length != 2 || !changed.Contains(playBullet.FullName) || !changed.Contains(head.FullName))
    throw new InvalidOperationException("unexpected CIL changes: " + string.Join(", ", changed));
if (after[playBullet.FullName] != before[playBullet.FullName].Replace(oldReference.FullName, installed.FullName))
    throw new InvalidOperationException("changed more than the one DOMove reference");
var verifiedHead = Types(verified.Types).Single(t => t.FullName == "ET.InitHeadInfoEvent").Methods.Single(m => m.Name == "Run");
if (FlowShape(verifiedHead, 6) != originalHeadShape ||
    !verifiedHead.Body.Instructions.Take(6).Select(i => i.OpCode).SequenceEqual(new[] { OpCodes.Ldarg_1, OpCodes.Ldfld, OpCodes.Callvirt, OpCodes.Callvirt, OpCodes.Brtrue, OpCodes.Ret }))
    throw new InvalidOperationException("head-info repair changed the original body beyond its null guard");
Console.WriteLine($"Validated: {before.Count} methods compared; exactly one call reference and one six-instruction MyUnit null guard repaired");
Console.WriteLine($"Before: {oldReference.FullName}");
Console.WriteLine($"After: {installed.FullName}");
Console.WriteLine($"Output SHA256: {Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(output))).ToLowerInvariant()}");

static IEnumerable<TypeDefinition> Types(IEnumerable<TypeDefinition> source) =>
    source.SelectMany(t => new[] { t }.Concat(Types(t.NestedTypes)));
static string Definitions(ModuleDefinition module) => string.Join("\n", Types(module.Types).Select(t =>
    $"{t.FullName}|{t.Attributes}|{t.BaseType}|" + string.Join(";", t.Fields.Select(f => $"{f.FullName}|{f.Attributes}")) + "|" +
    string.Join(";", t.Methods.Select(m => $"{m.FullName}|{m.Attributes}|{m.ImplAttributes}"))));
static Dictionary<string, string> Bodies(ModuleDefinition module) => Types(module.Types).SelectMany(t => t.Methods)
    .ToDictionary(m => m.FullName, m => !m.HasBody ? "<no body>" :
        string.Join("\n", m.Body.Instructions.Select(i => $"{i.Offset:x4}:{i.OpCode}:{Operand(i.Operand)}")) +
        "\nlocals:" + string.Join(";", m.Body.Variables.Select(v => v.VariableType.FullName)) +
        "\nhandlers:" + string.Join(";", m.Body.ExceptionHandlers.Select(h =>
            $"{h.HandlerType}:{h.CatchType}:{h.TryStart?.Offset}:{h.TryEnd?.Offset}:{h.HandlerStart?.Offset}:{h.HandlerEnd?.Offset}:{h.FilterStart?.Offset}")));
static string Operand(object? value) => value switch {
    null => "", Instruction i => i.Offset.ToString("x4"),
    Instruction[] items => string.Join(",", items.Select(i => i.Offset.ToString("x4"))),
    MethodReference m => m.FullName, FieldReference f => f.FullName,
    TypeReference t => t.FullName, _ => value.ToString() ?? ""
};
static string FlowShape(MethodDefinition method, int skip = 0) {
    var instructions = method.Body.Instructions.Skip(skip).ToArray();
    var indexes = instructions.Select((instruction, index) => (instruction, index)).ToDictionary(pair => pair.instruction, pair => pair.index);
    return string.Join("\n", instructions.Select(i => i.OpCode + ":" + (i.Operand switch {
        Instruction target => indexes[target].ToString(),
        Instruction[] targets => string.Join(",", targets.Select(target => indexes[target])), _ => Operand(i.Operand)
    })));
}

sealed class GameAssemblyResolver(string directory) : DefaultAssemblyResolver {
    public override AssemblyDefinition Resolve(AssemblyNameReference name) =>
        Resolve(name, new ReaderParameters { AssemblyResolver = this });
    public override AssemblyDefinition Resolve(AssemblyNameReference name, ReaderParameters parameters) {
        var filename = name.Name switch { "Unity.Hotfix" => "Hotfix.dll", "Unity.HotfixView" => "HotfixView.dll", _ => null };
        if (filename is not null && File.Exists(Path.Combine(directory, filename))) {
            parameters.AssemblyResolver = this;
            parameters.InMemory = true;
            parameters.ReadSymbols = false;
            return AssemblyDefinition.ReadAssembly(Path.Combine(directory, filename), parameters);
        }
        return base.Resolve(name, parameters);
    }
}
