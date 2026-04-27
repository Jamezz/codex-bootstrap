plugins {
    application
}

val javaVersion = providers.gradleProperty("javaVersion")
    .map(String::toInt)
    .orElse(21)

val useExactJavaToolchain = providers.gradleProperty("useExactJavaToolchain")
    .map(String::toBoolean)
    .orElse(false)

val supermetaRulesScript = layout.projectDirectory.file("../../tools/supermeta-rules/check.py")

java {
    if (useExactJavaToolchain.get()) {
        toolchain {
            languageVersion = javaVersion.map(JavaLanguageVersion::of)
        }
    }
}

application {
    mainClass = "com.example.App"
}

dependencies {
    testImplementation(platform("org.junit:junit-bom:5.11.4"))
    testImplementation("org.junit.jupiter:junit-jupiter")
    testRuntimeOnly("org.junit.platform:junit-platform-launcher")
}

tasks.test {
    useJUnitPlatform()
}

tasks.withType<JavaCompile>().configureEach {
    options.release = javaVersion
}

tasks.register<Exec>("verifySupermetaRules") {
    description = "Runs shared Supermeta rules for this template."
    group = "verification"

    inputs.file("supermeta-rules.json")
    inputs.files(fileTree("src/main"))

    commandLine(
        "python3",
        supermetaRulesScript.asFile.absolutePath,
        "--config",
        layout.projectDirectory.file("supermeta-rules.json").asFile.absolutePath,
        "--root",
        layout.projectDirectory.asFile.absolutePath,
    )
}

tasks.check {
    dependsOn("verifySupermetaRules")
}
