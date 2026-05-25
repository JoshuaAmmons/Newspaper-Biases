###############################################################################
# reproduce_all.R
# Master pipeline runner for "The Political Economy of Newspaper Bias".
#
# Renders the numbered R Markdown notebooks in order, each in its OWN R process
# (so a large model object or a segfault in one step can't poison the next).
#
# Usage (PowerShell):
#   & "C:/Program Files/R/R-4.4.1/bin/Rscript.exe" reproduce_all.R        # all steps
#   & "C:/Program Files/R/R-4.4.1/bin/Rscript.exe" reproduce_all.R 7      # from step 7
#   & "C:/Program Files/R/R-4.4.1/bin/Rscript.exe" reproduce_all.R 9 11   # steps 9..11
#
# Prerequisites:
#   * install_packages.R has been run; requirements.txt installed (CUDA torch).
#   * External shock extracts are dropped under data_raw/ (see docs/DATA_SOURCES.md)
#     BEFORE step 08; an API key is set BEFORE step 05 (GEMINI_API_KEY / ANTHROPIC_API_KEY).
###############################################################################

# Portable: env var overrides, else auto-detect. Run from anywhere in the project tree.
PROJECT_ROOT <- Sys.getenv("CAPLAN_ROOT")
if (PROJECT_ROOT == "")
  PROJECT_ROOT <- tryCatch(rprojroot::find_root(rprojroot::has_file("_config.R")),
                           error = function(e) getwd())
RSCRIPT <- Sys.getenv("CAPLAN_R")
if (!nzchar(RSCRIPT))
  RSCRIPT <- file.path(R.home("bin"), if (.Platform$OS.type == "windows") "Rscript.exe" else "Rscript")
PANDOC <- Sys.getenv("CAPLAN_PANDOC",
                     unset = "C:/Program Files/RStudio/resources/app/bin/quarto/bin/tools")

steps <- list(
  list(n =  0, file = "rmd/00_setup.Rmd",                note = "Verify R + Python + GPU + packages"),
  list(n =  1, file = "rmd/01_download_data.Rmd",        note = "Download American Stories -> data_parquet/"),
  list(n =  2, file = "rmd/02_clean_articles.Rmd",       note = "OCR filter, normalize, partition -> articles_cleaned/"),
  list(n =  3, file = "rmd/03_geolink_newspapers.Rmd",   note = "LCCN/title -> county FIPS crosswalk"),
  list(n =  4, file = "rmd/04_sample_for_labeling.Rmd",  note = "Stratified + positive-oversampled label queue"),
  list(n =  5, file = "rmd/05_build_training_set.Rmd",   note = "LLM weak-labels + human audit -> train/dev/test"),
  list(n =  6, file = "rmd/06_score_corpus.Rmd",         note = "Train RoBERTa, score corpus, calibrate"),
  list(n =  7, file = "rmd/07_build_panel.Rmd",          note = "Aggregate -> county-year/month bias panel"),
  list(n =  8, file = "rmd/08_build_shocks.Rmd",         note = "Build 4 shock datasets, merge to panel"),
  list(n =  9, file = "rmd/09_estimate_did.Rmd",         note = "Staggered DiD + exposure + event studies"),
  list(n = 10, file = "rmd/10_robustness.Rmd",           note = "Pre-trends, placebos, HonestDiD, LOO, excess"),
  list(n = 11, file = "rmd/11_figures_tables.Rmd",       note = "Figures + tables -> figures/, tables/, Overleaf")
)

args <- commandArgs(trailingOnly = TRUE)
start_step <- if (length(args) >= 1) as.integer(args[1]) else 0L
end_step   <- if (length(args) >= 2) as.integer(args[2]) else 11L

cat("================================================================\n")
cat("  reproduce_all.R — Newspaper Bias pipeline\n")
cat("  Steps", start_step, "to", end_step, "| start", format(Sys.time()), "\n")
cat("================================================================\n")

overall <- Sys.time(); results <- list()
for (s in steps) {
  if (s$n < start_step || s$n > end_step) next
  t0 <- Sys.time()
  cat(sprintf("\n--- Step %02d: %s ---\n  %s\n", s$n, s$file, s$note))

  rmd  <- normalizePath(file.path(PROJECT_ROOT, s$file), winslash = "/", mustWork = TRUE)
  html <- file.path(PROJECT_ROOT, "output", "html",
                    gsub("\\.Rmd$", ".html", basename(s$file)))
  # Only pin RSTUDIO_PANDOC if that dir exists; otherwise rmarkdown finds system pandoc.
  pandoc_prefix <- if (dir.exists(PANDOC)) sprintf("Sys.setenv(RSTUDIO_PANDOC='%s'); ", PANDOC) else ""
  expr <- sprintf(
    "%srmarkdown::render('%s', output_file='%s', envir=new.env(parent=globalenv()), quiet=FALSE)",
    pandoc_prefix, rmd, normalizePath(html, winslash = "/", mustWork = FALSE))
  code <- system2(RSCRIPT, args = c("-e", shQuote(expr)), wait = TRUE)

  elapsed <- round(as.numeric(difftime(Sys.time(), t0, units = "mins")), 1)
  results[[as.character(s$n)]] <- list(n = s$n, ok = code == 0, min = elapsed)
  if (code == 0) cat(sprintf("  SUCCESS (%.1f min)\n", elapsed))
  else {
    cat(sprintf("  FAILED (exit %d, %.1f min)\n", code, elapsed))
    cat(sprintf("  Fix and resume:  Rscript reproduce_all.R %d\n", s$n))
    quit(status = 1)
  }
}

cat("\n================================================================\n")
cat("  DONE in", round(as.numeric(difftime(Sys.time(), overall, units = "mins")), 1), "min\n")
for (r in results)
  cat(sprintf("  [%s] step %02d  (%.1f min)\n", if (r$ok) "OK" else "FAIL", r$n, r$min))
cat("  Outputs: figures/, tables/, and the Overleaf sync dir.\n")
cat("================================================================\n")
