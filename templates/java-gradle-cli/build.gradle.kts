import org.gradle.api.plugins.quality.Checkstyle

plugins {
    application
    checkstyle
}

val javaVersion = providers.gradleProperty("javaVersion")
    .map(String::toInt)
    .orElse(21)

val lombokVersion = providers.gradleProperty("lombokVersion")
    .orElse("1.18.44")

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

checkstyle {
    toolVersion = "13.3.0"
    configDirectory = layout.projectDirectory.dir("config/checkstyle")
}

dependencies {
    compileOnly("org.projectlombok:lombok:${lombokVersion.get()}")
    annotationProcessor("org.projectlombok:lombok:${lombokVersion.get()}")

    testImplementation(platform("org.junit:junit-bom:5.11.4"))
    testImplementation("org.junit.jupiter:junit-jupiter")
    testCompileOnly("org.projectlombok:lombok:${lombokVersion.get()}")
    testAnnotationProcessor("org.projectlombok:lombok:${lombokVersion.get()}")
    testRuntimeOnly("org.junit.platform:junit-platform-launcher")
}

tasks.test {
    useJUnitPlatform()
}

tasks.withType<JavaCompile>().configureEach {
    options.release = javaVersion
}

tasks.withType<Checkstyle>().configureEach {
    reports {
        xml.required = true
        html.required = true
    }
}

tasks.register<Exec>("verifySupermetaRules") {
    description = "Runs shared Supermeta rules for this template."
    group = "verification"

    inputs.file("supermeta-rules.json")
    inputs.files(fileTree("src/main"))
    inputs.files(fileTree("src/test"))

    commandLine(
        "python3",
        supermetaRulesScript.asFile.absolutePath,
        "--config",
        layout.projectDirectory.file("supermeta-rules.json").asFile.absolutePath,
        "--root",
        layout.projectDirectory.asFile.absolutePath,
        "--skip-callouts",
    )
}

tasks.check {
    dependsOn("verifySupermetaRules")
}
