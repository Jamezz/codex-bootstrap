using Generated.CsharpDotnetCli;

namespace Generated.CsharpDotnetCli.Tests;

public sealed class AppTests
{
    [Fact]
    public void GreetsDefaultProjectName()
    {
        CliResult result = App.Render([]);

        Assert.Equal(0, result.ExitCode);
        Assert.Equal("Hello from csharp-dotnet-cli!", result.Stdout);
        Assert.Equal(string.Empty, result.Stderr);
    }

    [Fact]
    public void GreetsProvidedName()
    {
        CliResult result = App.Render(["Ada", "Lovelace"]);

        Assert.Equal(0, result.ExitCode);
        Assert.Equal("Hello from Ada Lovelace!", result.Stdout);
        Assert.Equal(string.Empty, result.Stderr);
    }

    [Fact]
    public void RendersHelp()
    {
        CliResult result = App.Render(["--help"]);

        Assert.Equal(0, result.ExitCode);
        Assert.Equal("Usage: csharp-dotnet-cli [name]", result.Stdout);
        Assert.Equal(string.Empty, result.Stderr);
    }

    [Fact]
    public void RejectsBlankName()
    {
        CliResult result = App.Render([" "]);

        Assert.Equal(2, result.ExitCode);
        Assert.Equal(string.Empty, result.Stdout);
        Assert.Equal("Usage: csharp-dotnet-cli [name]", result.Stderr);
    }
}
