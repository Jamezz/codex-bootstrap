package com.example;

import java.io.*;

import lombok.*;

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
        int exitCode = new App(DEFAULT_NAME).run(args, System.out, System.err);
        if (exitCode != 0) {
            System.exit(exitCode);
        }
    }
}
