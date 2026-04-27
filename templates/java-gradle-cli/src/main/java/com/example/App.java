package com.example;

import java.io.*;

public final class App {
    private static final String DEFAULT_NAME = "java-gradle-cli";

    public int run(String[] args, PrintStream out, PrintStream err) {
        if (args.length > 0 && "--help".equals(args[0])) {
            out.println("Usage: java-gradle-cli [name]");
            return 0;
        }

        String name = args.length == 0 ? DEFAULT_NAME : String.join(" ", args).trim();
        if (name.isEmpty()) {
            err.println("Usage: java-gradle-cli [name]");
            return 2;
        }

        out.println("Hello from " + name + "!");
        return 0;
    }

    public static void main(String[] args) {
        int exitCode = new App().run(args, System.out, System.err);
        if (exitCode != 0) {
            System.exit(exitCode);
        }
    }
}
