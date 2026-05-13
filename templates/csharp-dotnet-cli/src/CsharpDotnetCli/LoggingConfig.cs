using System.Collections;
using System.Text.Json;

namespace Generated.CsharpDotnetCli;

public static class LoggingConfig
{
    public const string LoggerName = "csharp-dotnet-cli";

    private const string DefaultLogLevel = "warn";
    private const string DefaultLogFormat = "text";

    private static readonly IReadOnlyDictionary<string, LogLevel> LogLevels =
        new Dictionary<string, LogLevel>(StringComparer.OrdinalIgnoreCase)
        {
            ["trace"] = LogLevel.Trace,
            ["debug"] = LogLevel.Debug,
            ["info"] = LogLevel.Info,
            ["warn"] = LogLevel.Warn,
            ["error"] = LogLevel.Error,
            ["off"] = LogLevel.Off,
        };

    private static readonly IReadOnlyDictionary<string, LogFormat> LogFormats =
        new Dictionary<string, LogFormat>(StringComparer.OrdinalIgnoreCase)
        {
            ["text"] = LogFormat.Text,
            ["json"] = LogFormat.Json,
        };

    public static LoggingOptions FromEnvironment()
    {
        Dictionary<string, string?> values = Environment.GetEnvironmentVariables()
            .Cast<DictionaryEntry>()
            .ToDictionary(
                entry => (string)entry.Key,
                entry => entry.Value?.ToString(),
                StringComparer.Ordinal
            );
        return FromEnvironment(values);
    }

    public static LoggingOptions FromEnvironment(IReadOnlyDictionary<string, string?> environment)
    {
        string levelName = NormalizedValue(environment, "LOG_LEVEL", DefaultLogLevel);
        string formatName = NormalizedValue(environment, "LOG_FORMAT", DefaultLogFormat);

        if (!LogLevels.TryGetValue(levelName, out LogLevel level))
        {
            throw new LoggingConfigurationException(
                $"invalid LOG_LEVEL {Quote(environment.GetValueOrDefault("LOG_LEVEL"))}; expected one of: trace, debug, info, warn, error, off"
            );
        }

        if (!LogFormats.TryGetValue(formatName, out LogFormat format))
        {
            throw new LoggingConfigurationException(
                $"invalid LOG_FORMAT {Quote(environment.GetValueOrDefault("LOG_FORMAT"))}; expected one of: json, text"
            );
        }

        return new LoggingOptions(level, format);
    }

    public static RuntimeLogger CreateLoggerFromEnvironment(TextWriter stderr)
    {
        return new RuntimeLogger(stderr, LoggerName, FromEnvironment());
    }

    private static string NormalizedValue(
        IReadOnlyDictionary<string, string?> environment,
        string name,
        string defaultValue
    )
    {
        if (!environment.TryGetValue(name, out string? value) || string.IsNullOrWhiteSpace(value))
        {
            return defaultValue;
        }

        return value.Trim().ToLowerInvariant();
    }

    private static string Quote(string? value)
    {
        return value is null ? "null" : $"'{value}'";
    }
}

public sealed class RuntimeLogger
{
    private readonly TextWriter stderr;
    private readonly string loggerName;
    private readonly LoggingOptions options;

    public RuntimeLogger(TextWriter stderr, string loggerName, LoggingOptions options)
    {
        this.stderr = stderr;
        this.loggerName = loggerName;
        this.options = options;
    }

    public void Info(string message, IReadOnlyDictionary<string, object?> fields)
    {
        Write(LogLevel.Info, message, fields);
    }

    private void Write(LogLevel level, string message, IReadOnlyDictionary<string, object?> fields)
    {
        if (!IsEnabled(level))
        {
            return;
        }

        string timestamp = DateTimeOffset.UtcNow.ToString("yyyy-MM-dd'T'HH:mm:ss.fff'Z'");
        if (options.Format == LogFormat.Json)
        {
            Dictionary<string, object?> payload = new()
            {
                ["timestamp"] = timestamp,
                ["level"] = LevelName(level),
                ["logger"] = loggerName,
                ["message"] = message,
            };
            foreach (KeyValuePair<string, object?> field in fields.OrderBy(field => field.Key))
            {
                payload[field.Key] = field.Value;
            }

            stderr.WriteLine(JsonSerializer.Serialize(payload));
            return;
        }

        string fieldText = string.Join(
            string.Empty,
            fields.OrderBy(field => field.Key).Select(field => $" {field.Key}={field.Value}")
        );
        stderr.WriteLine($"{timestamp} {LevelName(level)} {loggerName} - {message}{fieldText}");
    }

    private bool IsEnabled(LogLevel level)
    {
        return options.Level != LogLevel.Off && level >= options.Level;
    }

    private static string LevelName(LogLevel level)
    {
        return level.ToString().ToLowerInvariant();
    }
}

public sealed record LoggingOptions(LogLevel Level, LogFormat Format);

public enum LogLevel
{
    Trace = 0,
    Debug = 1,
    Info = 2,
    Warn = 3,
    Error = 4,
    Off = 5,
}

public enum LogFormat
{
    Text,
    Json,
}

public sealed class LoggingConfigurationException : Exception
{
    public LoggingConfigurationException(string message)
        : base(message)
    {
    }
}
