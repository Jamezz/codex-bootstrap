package com.example;

import static org.junit.jupiter.api.Assertions.*;

import org.junit.jupiter.api.*;

final class AppTest {
    @Test
    void greetingIsStable() {
        assertEquals("Hello from java-gradle-cli!", new App().greeting());
    }
}
