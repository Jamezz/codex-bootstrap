use std::{env, error::Error, fmt};

#[derive(Clone, Copy, Debug, Eq, PartialEq, Ord, PartialOrd)]
enum LogLevel {
    Trace,
    Debug,
    Info,
    Warn,
    Error,
    Off,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum LogFormat {
    Text,
    Json,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct Logger {
    level: LogLevel,
    format: LogFormat,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LoggingConfigError {
    variable: &'static str,
    value: String,
    expected: &'static str,
}

impl Logger {
    pub fn from_env() -> Result<Self, LoggingConfigError> {
        let level = match env::var("LOG_LEVEL") {
            Ok(value) => parse_level(&value).ok_or_else(|| LoggingConfigError {
                variable: "LOG_LEVEL",
                value,
                expected: "trace, debug, info, warn, error, or off",
            })?,
            Err(_) => LogLevel::Warn,
        };

        let format = match env::var("LOG_FORMAT") {
            Ok(value) => parse_format(&value).ok_or_else(|| LoggingConfigError {
                variable: "LOG_FORMAT",
                value,
                expected: "text or json",
            })?,
            Err(_) => LogFormat::Text,
        };

        Ok(Self { level, format })
    }

    pub fn info(&self, message: &str) {
        self.write(LogLevel::Info, "INFO", message);
    }

    fn write(&self, level: LogLevel, label: &str, message: &str) {
        if !self.enabled(level) {
            return;
        }

        match self.format {
            LogFormat::Text => eprintln!("{label} {message}"),
            LogFormat::Json => eprintln!(
                "{{\"level\":\"{}\",\"message\":\"{}\"}}",
                label.to_ascii_lowercase(),
                escape_json(message)
            ),
        }
    }

    fn enabled(&self, level: LogLevel) -> bool {
        self.level != LogLevel::Off && level >= self.level
    }
}

impl fmt::Display for LoggingConfigError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            formatter,
            "{}={} is invalid; expected {}",
            self.variable, self.value, self.expected
        )
    }
}

impl Error for LoggingConfigError {}

fn parse_level(value: &str) -> Option<LogLevel> {
    match value.trim().to_ascii_lowercase().as_str() {
        "trace" => Some(LogLevel::Trace),
        "debug" => Some(LogLevel::Debug),
        "info" => Some(LogLevel::Info),
        "warn" | "warning" => Some(LogLevel::Warn),
        "error" => Some(LogLevel::Error),
        "off" => Some(LogLevel::Off),
        _ => None,
    }
}

fn parse_format(value: &str) -> Option<LogFormat> {
    match value.trim().to_ascii_lowercase().as_str() {
        "text" => Some(LogFormat::Text),
        "json" => Some(LogFormat::Json),
        _ => None,
    }
}

fn escape_json(value: &str) -> String {
    let mut escaped = String::new();
    for character in value.chars() {
        match character {
            '"' => escaped.push_str("\\\""),
            '\\' => escaped.push_str("\\\\"),
            '\n' => escaped.push_str("\\n"),
            '\r' => escaped.push_str("\\r"),
            '\t' => escaped.push_str("\\t"),
            control if control.is_control() => {
                escaped.push_str(&format!("\\u{:04x}", control as u32));
            }
            other => escaped.push(other),
        }
    }
    escaped
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_supported_levels() {
        assert_eq!(Some(LogLevel::Trace), parse_level("trace"));
        assert_eq!(Some(LogLevel::Warn), parse_level("warning"));
        assert_eq!(Some(LogLevel::Off), parse_level("off"));
    }

    #[test]
    fn rejects_unknown_level() {
        assert_eq!(None, parse_level("verbose"));
    }

    #[test]
    fn parses_supported_formats() {
        assert_eq!(Some(LogFormat::Text), parse_format("text"));
        assert_eq!(Some(LogFormat::Json), parse_format("json"));
    }

    #[test]
    fn escapes_json_message_text() {
        assert_eq!("quote\\\" slash\\\\ line\\n", escape_json("quote\" slash\\ line\n"));
    }

    #[test]
    fn default_warn_level_disables_info() {
        let logger = Logger {
            level: LogLevel::Warn,
            format: LogFormat::Text,
        };

        assert!(!logger.enabled(LogLevel::Info));
        assert!(logger.enabled(LogLevel::Error));
    }
}
