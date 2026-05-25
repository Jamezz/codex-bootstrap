pub fn render_greeting(args: &[String]) -> String {
    let name = args
        .first()
        .map(|value| value.trim())
        .filter(|value| !value.is_empty())
        .unwrap_or("world");

    format!("Hello, {name}!")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn renders_default_greeting() {
        assert_eq!("Hello, world!", render_greeting(&[]));
    }

    #[test]
    fn renders_named_greeting() {
        assert_eq!(
            "Hello, Ada Lovelace!",
            render_greeting(&[String::from("Ada Lovelace")])
        );
    }

    #[test]
    fn treats_blank_name_as_missing() {
        assert_eq!("Hello, world!", render_greeting(&[String::from("   ")]));
    }
}
