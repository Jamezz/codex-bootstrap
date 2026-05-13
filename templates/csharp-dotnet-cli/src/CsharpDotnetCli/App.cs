namespace Generated.CsharpDotnetCli;

public sealed class App
{
    public const string DefaultName = "csharp-dotnet-cli";
    public const string Usage = "Usage: csharp-dotnet-cli [name]";

    private readonly string defaultName;

    public App(string defaultName)
    {
        this.defaultName = defaultName;
    }

    public int Run(IReadOnlyList<string> args, TextWriter stdout, TextWriter stderr)
    {
        CliResult result = Render(args, defaultName);
        WriteResult(result, stdout, stderr);
        return result.ExitCode;
    }

    public static CliResult Render(IReadOnlyList<string> args, string defaultName = DefaultName)
    {
        if (args.Count > 0 && args[0] == "--help")
        {
            return new CliResult(0, Usage, string.Empty);
        }

        string name = args.Count == 0 ? defaultName : string.Join(" ", args).Trim();
        if (string.IsNullOrEmpty(name))
        {
            return new CliResult(2, string.Empty, Usage);
        }

        return new CliResult(0, $"Hello from {name}!", string.Empty);
    }

    private static void WriteResult(CliResult result, TextWriter stdout, TextWriter stderr)
    {
        if (!string.IsNullOrEmpty(result.Stdout))
        {
            stdout.WriteLine(result.Stdout);
        }

        if (!string.IsNullOrEmpty(result.Stderr))
        {
            stderr.WriteLine(result.Stderr);
        }
    }
}

public sealed record CliResult(int ExitCode, string Stdout, string Stderr);
