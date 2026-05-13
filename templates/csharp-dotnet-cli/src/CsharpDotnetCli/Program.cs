namespace Generated.CsharpDotnetCli;

public static class Program
{
    public static int Main(string[] args)
    {
        RuntimeLogger logger;
        try
        {
            logger = LoggingConfig.CreateLoggerFromEnvironment(Console.Error);
        }
        catch (LoggingConfigurationException error)
        {
            Console.Error.WriteLine($"Logging configuration error: {error.Message}");
            return 2;
        }

        int exitCode = new App(App.DefaultName).Run(args, Console.Out, Console.Error);
        logger.Info("command completed", new Dictionary<string, object?> { ["exitCode"] = exitCode });
        return exitCode;
    }
}
