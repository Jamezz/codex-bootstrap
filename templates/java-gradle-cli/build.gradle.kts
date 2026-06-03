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

val logbackVersion = providers.gradleProperty("logbackVersion")
    .orElse("1.5.32")

val logstashLogbackEncoderVersion = providers.gradleProperty("logstashLogbackEncoderVersion")
    .orElse("9.0")

val slf4jVersion = providers.gradleProperty("slf4jVersion")
    .orElse("2.0.17")

val useExactJavaToolchain = providers.gradleProperty("useExactJavaToolchain")
    .map(String::toBoolean)
    .orElse(false)

val generatedSupermetaRulesToolDir = layout.projectDirectory.dir("tools/supermeta-rules")
val supermetaRulesToolDir = if (generatedSupermetaRulesToolDir.asFile.isDirectory) {
    generatedSupermetaRulesToolDir
} else {
    layout.projectDirectory.dir("../../tools/supermeta-rules")
}
val supermetaRulesScript = supermetaRulesToolDir.file("check.py")
val supermetaRulesRequirements = supermetaRulesToolDir.file("requirements.txt")
val supermetaRulesVenv = layout.projectDirectory.dir(".gradle/supermeta-rules-venv")
val supermetaRulesPython = providers.provider {
    val executable = if (System.getProperty("os.name").lowercase().contains("windows")) {
        "Scripts/python.exe"
    } else {
        "bin/python"
    }
    supermetaRulesVenv.file(executable).asFile.absolutePath
}

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
    implementation("org.slf4j:slf4j-api:${slf4jVersion.get()}")
    implementation("ch.qos.logback:logback-classic:${logbackVersion.get()}")
    implementation("net.logstash.logback:logstash-logback-encoder:${logstashLogbackEncoderVersion.get()}")

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
    maxWarnings = Int.MAX_VALUE

    reports {
        xml.required = true
        html.required = true
    }
}

tasks.register<Exec>("installSupermetaRuleDependencies") {
    description = "Installs parser dependencies for shared Supermeta rules."
    group = "verification"

    inputs.file(supermetaRulesRequirements)
    outputs.dir(supermetaRulesVenv)

    commandLine("python3", "-m", "venv", supermetaRulesVenv.asFile.absolutePath)

    doLast {
        providers.exec {
            commandLine(
                supermetaRulesPython.get(),
                "-m",
                "pip",
                "install",
                "--quiet",
                "-r",
                supermetaRulesRequirements.asFile.absolutePath,
            )
        }.result.get().assertNormalExitValue()
    }
}

tasks.register<Exec>("verifySupermetaRules") {
    description = "Runs shared Supermeta rules for this template."
    group = "verification"

    dependsOn("installSupermetaRuleDependencies")

    inputs.file("supermeta-rules.json")
    inputs.file(supermetaRulesScript)
    inputs.file(supermetaRulesRequirements)
    inputs.files(fileTree(supermetaRulesToolDir))
    inputs.files(fileTree("src/main"))
    inputs.files(fileTree("src/test"))

    commandLine(
        supermetaRulesPython.get(),
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
