###############################################################################
# install_packages.R — one-time R dependency installation
#   Rscript install_packages.R
# Python deps are separate: pip install -r requirements.txt
###############################################################################

repos <- "https://cloud.r-project.org"

# CRAN packages used across the pipeline
cran <- c(
  # data wrangling + IO
  "data.table", "arrow", "dplyr", "tidyr", "stringi", "readr", "lubridate",
  "jsonlite", "httr2",                       # httr2 for the loc.gov API (geolink)
  "rprojroot",                               # portable project-root detection in notebooks
  # plotting / reporting
  "ggplot2", "patchwork", "scales", "knitr", "rmarkdown",
  # econometrics
  "fixest",            # TWFE / event study
  "did",               # Callaway & Sant'Anna group-time ATT
  "fect",              # interactive fixed effects / matrix completion
  # geography / maps
  "usmap", "sf",
  # misc
  "remotes"
)

installed <- rownames(installed.packages())
to_install <- setdiff(cran, installed)
if (length(to_install)) {
  message("Installing CRAN packages: ", paste(to_install, collapse = ", "))
  install.packages(to_install, repos = repos)
} else {
  message("All CRAN packages already installed.")
}

# Packages that are sometimes only on GitHub or need explicit installs
# (mirror the Ideas repo, which uses these for staggered-DiD robustness)
gh <- list(
  DIDmultiplegt   = "chaisemartinPackages/DIDmultiplegt",       # de Chaisemartin & D'Haultfoeuille
  DIDmultiplegtDYN = "chaisemartinPackages/did_multiplegt_dyn", # dynamic dCDH (event study)
  HonestDiD       = "asheshrambachan/HonestDiD"                 # Rambachan & Roth sensitivity
)
for (pkg in names(gh)) {
  if (!pkg %in% rownames(installed.packages())) {
    message("Installing ", pkg, " from GitHub: ", gh[[pkg]])
    try(remotes::install_github(gh[[pkg]], upgrade = "never"), silent = TRUE)
  }
}

message("\nDone. Verify with: library(<pkg>) for each.")
message("If a GitHub package fails, install Rtools and retry remotes::install_github().")
