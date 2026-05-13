using System.Text.Json;

using Generated.CsharpDotnetCli;

namespace Generated.CsharpDotnetCli.Tests;

public sealed class LoggingConfigTests
{
    [Fact]
    public void DefaultsToQuietTextLogging()
    {
        LoggingOptions options = LoggingConfig.FromEnvironment(new Dictionary<string, string?>());

        Assert.Equal(LogLevel.Warn, options.Level);
        Assert.Equal(LogFormat.Text, options.Format);
    }

    [Fact]
    public void ParsesCaseInsensitiveValues()
    {
        LoggingOptions options = LoggingConfig.FromEnvironment(
            new Dictionary<string, string?>
            {
                ["LOG_LEVEL"] = "INFO",
                ["LOG_FORMAT"] = "JSON",
            }
        );

        Assert.Equal(LogLevel.Info, options.Level);
        Assert.Equal(LogFormat.Json, options.Format);
    }

    [Fact]
    public void RejectsInvalidLevel()
    {
        LoggingConfigurationException error = Assert.Throws<LoggingConfigurationException>(
            () => LoggingConfig.FromEnvironment(new Dictionary<string, string?> { ["LOG_LEVEL"] = "verbose" })
        );

        Assert.Contains("LOG_LEVEL", error.Message, StringComparison.Ordinal);
    }

    [Fact]
    public void RejectsInvalidFormat()
    {
        LoggingConfigurationException error = Assert.Throws<LoggingConfigurationException>(
            () => LoggingConfig.FromEnvironment(new Dictionary<string, string?> { ["LOG_FORMAT"] = "yaml" })
        );

        Assert.Contains("LOG_FORMAT", error.Message, StringComparison.Ordinal);
    }

    [Fact]
    public void WritesTextLogsToStderr()
    {
        StringWriter stderr = new();
        RuntimeLogger logger = new(
            stderr,
            "csharp-dotnet-cli",
            new LoggingOptions(LogLevel.Info, LogFormat.Text)
        );

        logger.Info("command completed", new Dictionary<string, object?> { ["exitCode"] = 0 });

        string output = stderr.ToString();
        Assert.Contains("info csharp-dotnet-cli - command completed exitCode=0", output, StringComparison.Ordinal);
    }

    [Fact]
    public void WritesJsonLogsToStderr()
    {
        StringWriter stderr = new();
        RuntimeLogger logger = new(
            stderr,
            "csharp-dotnet-cli",
            new LoggingOptions(LogLevel.Info, LogFormat.Json)
        );

        logger.Info("command completed", new Dictionary<string, object?> { ["exitCode"] = 0 });

        using JsonDocument document = JsonDocument.Parse(stderr.ToString());
        JsonElement root = document.RootElement;
        Assert.Equal("info", root.GetProperty("level").GetString());
        Assert.Equal("csharp-dotnet-cli", root.GetProperty("logger").GetString());
        Assert.Equal("command completed", root.GetProperty("message").GetString());
        Assert.Equal(0, root.GetProperty("exitCode").GetInt32());
        Assert.True(root.TryGetProperty("timestamp", out _));
    }
}
