package com.example;

public final class App {
    private static final String GREETING = "Hello from java-gradle-cli!";

    public String greeting() {
        return GREETING;
    }

    public static void main(String[] args) {
        System.out.println(new App().greeting());
    }
}
