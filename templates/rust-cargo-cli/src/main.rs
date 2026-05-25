mod cli;
mod logging;

use std::{env, process};

fn main() {
    let logger = match logging::Logger::from_env() {
        Ok(logger) => logger,
        Err(error) => {
            eprintln!("logging configuration error: {error}");
            process::exit(2);
        }
    };

    logger.info("starting rust-cargo-cli");

    let args = env::args().skip(1).collect::<Vec<_>>();
    println!("{}", cli::render_greeting(&args));
}
