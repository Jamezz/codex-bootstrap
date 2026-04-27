package com.example;

import java.io.*;

import static net.logstash.logback.argument.StructuredArguments.*;

import lombok.*;
import org.slf4j.*;

@RequiredArgsConstructor
public final class App {
    private static final String DEFAULT_NAME = "java-gradle-cli";

    private final String defaultName;

    public int run(String[] args, PrintStream out, PrintStream err) {
        if (args.length > 0 && "--help".equals(args[0])) {
            out.println("Usage: java-gradle-cli [name]");
            return 0;
        }

        String name = args.length == 0 ? defaultName : String.join(" ", args).trim();
        if (name.isEmpty()) {
            err.println("Usage: java-gradle-cli [name]");
            return 2;
        }

        out.println("Hello from " + name + "!");
        return 0;
    }

    public static void main(String[] args) {
        Logger logger;
        try {
            LoggingConfig.configureFromEnvironment();
            logger = LoggerFactory.getLogger(App.class);
        } catch (IllegalArgumentException error) {
            System.err.println("Logging configuration error: " + error.getMessage());
            System.exit(2);
            return;
        }

        int exitCode = new App(DEFAULT_NAME).run(args, System.out, System.err);
        logger.info("command completed {}", keyValue("exitCode", exitCode));
        if (exitCode != 0) {
            System.exit(exitCode);
        }
    }
}
