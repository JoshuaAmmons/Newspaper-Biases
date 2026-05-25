# _config.R — Shared project configuration (portable: no machine-specific paths required).
#
# Source at the top of every script/notebook. The notebooks set PROJECT_ROOT first
# (env var CAPLAN_ROOT, else auto-detected by searching upward for this file), then source
# this. Standalone use: set CAPLAN_ROOT, or just run from anywhere inside the project tree.
#
# Optional environment overrides (all have sensible auto-detected defaults):
#   CAPLAN_ROOT               project root directory
#   CAPLAN_R                  path to Rscript (default: the running R's Rscript)
#   CAPLAN_PYTHON             path to python  (default: python on PATH)
#   CAPLAN_PANDOC             pandoc dir      (default: system pandoc via rmarkdown)
#   CAPLAN_OVERLEAF_FIGURES   extra dir to also write figures to (e.g. an Overleaf sync folder)
#   CAPLAN_OVERLEAF_TABLES    extra dir to also write tables to

# ---- Project root (portable) -------------------------------------------------
if (!exists("PROJECT_ROOT") || !nzchar(PROJECT_ROOT)) PROJECT_ROOT <- Sys.getenv("CAPLAN_ROOT")
if (!nzchar(PROJECT_ROOT)) {
  d <- normalizePath(getwd(), winslash = "/")
  while (!file.exists(file.path(d, "_config.R"))) {
    parent <- dirname(d)
    if (parent == d) stop("Could not locate the project root. Set CAPLAN_ROOT or run from inside the project.")
    d <- parent
  }
  PROJECT_ROOT <- d
}

# ---- Paths -------------------------------------------------------------------
DATA_RAW      <- file.path(PROJECT_ROOT, "data_raw")        # external shock downloads
DATA_PARQUET  <- file.path(PROJECT_ROOT, "data_parquet")    # American Stories + scored articles
DATA_PANELS   <- file.path(PROJECT_ROOT, "data_panels")     # county-period panels, crosswalks
MODELS_DIR    <- file.path(PROJECT_ROOT, "models")          # trained classifiers, calibrators
FIGURES_DIR   <- file.path(PROJECT_ROOT, "figures")
TABLES_DIR    <- file.path(PROJECT_ROOT, "tables")
OUTPUT_HTML   <- file.path(PROJECT_ROOT, "output", "html")
OUTPUT_LOGS   <- file.path(PROJECT_ROOT, "output", "logs")

# Optional extra sync targets (e.g. Overleaf). Empty string => skipped.
OVERLEAF_FIGURES <- Sys.getenv("CAPLAN_OVERLEAF_FIGURES")
OVERLEAF_TABLES  <- Sys.getenv("CAPLAN_OVERLEAF_TABLES")

# ---- Executables (auto-detected; override via env vars) ----------------------
R_EXE <- Sys.getenv("CAPLAN_R")
if (!nzchar(R_EXE))
  R_EXE <- file.path(R.home("bin"), if (.Platform$OS.type == "windows") "Rscript.exe" else "Rscript")

PYTHON_EXE <- Sys.getenv("CAPLAN_PYTHON")
if (!nzchar(PYTHON_EXE)) { w <- Sys.which("python"); PYTHON_EXE <- if (nzchar(w)) unname(w) else "python" }

# Pandoc: only pin it if the given dir exists; otherwise rmarkdown finds system pandoc.
pandoc_dir <- Sys.getenv("CAPLAN_PANDOC",
                         unset = "C:/Program Files/RStudio/resources/app/bin/quarto/bin/tools")
if (dir.exists(pandoc_dir)) Sys.setenv(RSTUDIO_PANDOC = pandoc_dir)

# ---- Ensure directories exist ------------------------------------------------
.dirs <- c(DATA_RAW, DATA_PARQUET, DATA_PANELS, MODELS_DIR,
           FIGURES_DIR, TABLES_DIR, OUTPUT_HTML, OUTPUT_LOGS)
.dirs <- c(.dirs, Filter(nzchar, c(OVERLEAF_FIGURES, OVERLEAF_TABLES)))
for (d in .dirs) dir.create(d, recursive = TRUE, showWarnings = FALSE)

# ---- Analysis windows --------------------------------------------------------
YEARS_ALL      <- as.character(1774:1960)   # full corpus span
YEARS_ANALYSIS <- as.character(1895:1945)   # where county shocks exist; primary analysis
SEED <- 42
set.seed(SEED)

# ---- Fixed event dates (national shocks; Design 3) ---------------------------
EVENTS <- list(
  wwi_entry        = as.Date("1917-04-06"),  # U.S. entry into WWI
  immigration_1924 = as.Date("1924-05-26")   # Immigration Act of 1924 (Johnson-Reed)
)

# ---- BIASES registry ---------------------------------------------------------
# Each bias is an outcome. `seed_lexicon` (R/helpers.R BIAS_SEED_LEXICONS) is used ONLY to
# oversample positives when sampling for labeling (rmd/04). The final measure is the staged
# RoBERTa classifier, NOT the lexicon.
BIASES <- list(
  anti_market = list(
    label = "Anti-market bias",
    definition = "Treats markets, competition, profit, prices, middlemen, or voluntary exchange as harmful in themselves (not a specific fraud/monopoly).",
    primary_shock = "bank_distress"),
  anti_foreign = list(
    label = "Anti-foreign bias",
    definition = "Portrays immigrants, foreign producers, imports, or external actors as inherently threatening to domestic prosperity/jobs/order.",
    primary_shock = "wwi_exposure"),
  make_work = list(
    label = "Make-work bias",
    definition = "Treats labor-saving innovation/efficiency as harmful because it reduces employment; judges policy by job preservation regardless of productivity.",
    primary_shock = "mechanization"),
  pessimistic = list(
    label = "Pessimistic bias",
    definition = "Depicts conditions as worsening/disastrous/permanently precarious beyond what underlying conditions warrant (measured as EXCESS pessimism).",
    primary_shock = "climate")
)

# ---- SHOCKS registry ---------------------------------------------------------
# Each shock defines a treatment design. See docs/DATA_SOURCES.md for how to obtain each.
SHOCKS <- list(
  bank_distress = list(
    bias = "anti_market", source = "NHGIS county FDIC bank deposits (ICPSR Study 7)",
    raw_dir = file.path(DATA_RAW, "nhgis_bank_deposits"),
    years = 1920:1936, grain = "county_year",
    treat_def = "top-decile YoY deposit decline (binary, staggered) or dlog deposits (continuous)",
    estimator = "staggered_did"),
  climate = list(
    bias = "pessimistic", source = "NOAA nClimDiv county monthly temp/precip/PDSI",
    raw_dir = file.path(DATA_RAW, "noaa_nclimdiv"),
    years = 1895:1945, grain = "county_month",
    treat_def = "z-scored climate anomaly (drought / temp / precip) vs county climatology",
    estimator = "did_month"),
  mortality = list(
    bias = "pessimistic", source = "NHGIS county vital statistics (births/deaths)",
    raw_dir = file.path(DATA_RAW, "nhgis_vital"),
    years = 1915:1945, grain = "county_year",
    treat_def = "mortality-rate spike (incl. 1918 influenza)", estimator = "did_year"),
  wwi_exposure = list(
    bias = "anti_foreign", source = "IPUMS Full Count / NHGIS county German-born share 1910",
    raw_dir = file.path(DATA_RAW, "exposure_foreignborn"),
    event = "wwi_entry", grain = "county_exposure",
    treat_def = "post-1917 x county German-born share (1910)", estimator = "exposure_did"),
  immigration_1924_exposure = list(
    bias = "anti_foreign",
    source = "IPUMS Full Count / NHGIS county foreign-born / S&E-European share (~1920)",
    raw_dir = file.path(DATA_RAW, "exposure_foreignborn"),
    event = "immigration_1924", grain = "county_exposure",
    treat_def = "post-1924 x county foreign-born (or SE-European) share",
    estimator = "exposure_did"),
  mechanization = list(
    bias = "make_work", source = "NHGIS Census of Agriculture 1925 & 1935 (tractors/machinery)",
    raw_dir = file.path(DATA_RAW, "nhgis_agcensus"),
    years = c(1925, 1935), grain = "county_census",
    treat_def = "high vs low intercensal jump in mechanization (tractors/machinery per farm)",
    estimator = "did_2period")
)

SHOCK_BUILD_ORDER <- c("bank_distress", "climate", "mortality",
                       "wwi_exposure", "immigration_1924_exposure", "mechanization")

# Create each shock's raw-data subdirectory so it's clear where to drop each extract
# (see docs/DATA_SOURCES.md). Empty until you add the NHGIS/NOAA/IPUMS files.
for (.s in SHOCKS) dir.create(.s$raw_dir, recursive = TRUE, showWarnings = FALSE)

# ---- Model paths -------------------------------------------------------------
RELEVANCE_MODEL_DIR <- file.path(MODELS_DIR, "roberta_relevance")
STANCE_MODEL_DIR    <- file.path(MODELS_DIR, "roberta_stance")   # 4 bias heads
CALIBRATORS_RDS     <- file.path(MODELS_DIR, "calibrators.rds")
SCORED_DIR          <- file.path(DATA_PARQUET, "articles_scored")

# ---- Output helpers ----------------------------------------------------------
# Always writes to the local figures/ (or tables/) dir; ALSO writes to the Overleaf dir
# if CAPLAN_OVERLEAF_* is set. So the repo is fully runnable without Overleaf/Dropbox.
save_figure <- function(plot_obj, filename, width = 7, height = 5, dpi = 300) {
  for (dir in Filter(nzchar, c(FIGURES_DIR, OVERLEAF_FIGURES))) {
    if (!dir.exists(dir)) next
    ggplot2::ggsave(file.path(dir, paste0(filename, ".pdf")),
                    plot = plot_obj, width = width, height = height, dpi = dpi)
    ggplot2::ggsave(file.path(dir, paste0(filename, ".png")),
                    plot = plot_obj, width = width, height = height, dpi = dpi)
  }
}
save_table <- function(tex_string, filename) {
  for (dir in Filter(nzchar, c(TABLES_DIR, OVERLEAF_TABLES))) {
    if (!dir.exists(dir)) next
    writeLines(tex_string, file.path(dir, paste0(filename, ".tex")))
  }
}

message("Config loaded. Project root: ", PROJECT_ROOT)
