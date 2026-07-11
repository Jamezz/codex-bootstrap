package main

import (
	"bytes"
	"fmt"
	"go/format"
	"io/fs"
	"os"
	"path/filepath"
)

func main() {
	findings := 0
	err := filepath.WalkDir(".", func(path string, entry fs.DirEntry, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}
		if entry.IsDir() {
			if skipFormatDirectory(path) {
				return filepath.SkipDir
			}
			return nil
		}
		if filepath.Ext(path) != ".go" {
			return nil
		}

		source, err := os.ReadFile(path)
		if err != nil {
			return err
		}
		formatted, err := format.Source(source)
		if err != nil {
			return fmt.Errorf("format %s: %w", path, err)
		}
		if !bytes.Equal(source, formatted) {
			fmt.Fprintln(os.Stderr, path)
			findings++
		}
		return nil
	})
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	if findings > 0 {
		fmt.Fprintln(os.Stderr, "gofmt check failed")
		os.Exit(1)
	}
}

func skipFormatDirectory(path string) bool {
	base := filepath.Base(path)
	return base == ".git" || base == "node_modules" || base == "target" || base == "vendor"
}
