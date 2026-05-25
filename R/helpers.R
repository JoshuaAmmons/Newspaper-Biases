# R/helpers.R — Shared utility functions and seed lexicons.
# Source after _config.R.

# ---- Text utilities ----------------------------------------------------------

#' Count words in a character vector
count_words <- function(x) stringi::stri_count_words(x)

#' Share of non-alphabetic characters (OCR-quality proxy; high = noisy scan)
share_nonalpha <- function(x) {
  total <- nchar(x)
  alpha <- nchar(gsub("[^a-zA-Z]", "", x))
  ifelse(total > 0, 1 - alpha / total, NA_real_)
}

#' Parse a page field (e.g., "p1" -> 1)
parse_page <- function(x) as.integer(gsub("[^0-9]", "", x))

#' Lexicon hit-rate per 1000 words. Used ONLY to oversample positives when
#' sampling for labeling — never as the final bias measure.
lexicon_score <- function(text, lexicon, ignore_case = TRUE) {
  if (ignore_case) { text <- tolower(text); lexicon <- tolower(lexicon) }
  pattern <- paste0("\\b(", paste(lexicon, collapse = "|"), ")\\b")
  matches <- stringi::stri_count_regex(text, pattern)
  words   <- stringi::stri_count_words(text)
  ifelse(words > 0, matches / words * 1000, 0)
}

#' Z-score against a reference mean/sd (for climate anomalies, etc.)
zscore <- function(x, mu = mean(x, na.rm = TRUE), sigma = sd(x, na.rm = TRUE)) {
  ifelse(is.finite(sigma) & sigma > 0, (x - mu) / sigma, NA_real_)
}

#' Normalize a county FIPS to 5-character zero-padded string ("01001").
fips5 <- function(state, county) {
  sprintf("%02d%03d", as.integer(state), as.integer(county))
}

# ---- Calibration -------------------------------------------------------------

#' Isotonic calibration: fit on (predicted, actual); returns a calibration function.
#' Same approach as the Ideas repo so aggregated probability shares are meaningful.
fit_isotonic <- function(predicted, actual) {
  keep <- !is.na(predicted) & !is.na(actual)
  predicted <- predicted[keep]; actual <- actual[keep]
  ord <- order(predicted)
  iso <- isoreg(predicted[ord], actual[ord])
  fit_df <- aggregate(y ~ x, data = data.frame(x = iso$x, y = iso$yf), FUN = mean)
  fit_df <- fit_df[order(fit_df$x), ]
  if (nrow(fit_df) < 2) {
    const_val <- mean(actual)
    message("Warning: isotonic calibration degenerate, using constant = ",
            round(const_val, 4))
    return(function(new_pred) rep(const_val, length(new_pred)))
  }
  function(new_pred) approx(fit_df$x, fit_df$y, xout = new_pred, rule = 2)$y
}

# ---- Seed lexicons for SAMPLING ONLY -----------------------------------------
# Historically-flavored seed terms to find candidate positives for each bias when
# drawing the labeling sample (rmd/04). NOT the measurement instrument. Coverage
# matters more than precision here (the LLM/human + RoBERTa decide actual labels).
BIAS_SEED_LEXICONS <- list(
  anti_market = c(
    "profiteer", "profiteers", "speculator", "speculators", "usury", "usurer",
    "middleman", "middlemen", "monopoly", "trusts", "the trust", "plutocrat",
    "robber baron", "money power", "money changers", "grasping greed",
    "ruinous competition", "cutthroat competition", "exploitation of labor",
    "blood money", "parasite", "gouging", "extortion of trade", "soulless corporation"
  ),
  anti_foreign = c(
    "foreign menace", "alien menace", "alien horde", "immigrant flood",
    "cheap foreign labor", "pauper labor", "undesirable aliens", "unassimilable",
    "foreign competition", "dumping of foreign", "invasion of immigrants",
    "contract labor", "yellow peril", "the foreigner", "hordes of immigrants",
    "flood of immigrants", "scum of europe", "menace to american labor"
  ),
  make_work = c(
    "throws men out of work", "thrown out of work by", "displaced by machinery",
    "labor-saving", "labor saving machine", "machines that rob", "idle hands",
    "technological unemployment", "make work", "preserve jobs", "hand labor",
    "ruin of the workingman", "machine takes the bread", "men replaced by machines",
    "featherbedding", "spread the work"
  ),
  pessimistic = c(
    "ruin", "ruined", "doomed", "doom", "collapse", "no recovery",
    "never recover", "permanent depression", "downfall", "catastrophe",
    "bound to fail", "hopeless", "going to the dogs", "ruinous decline",
    "the end is near", "irretrievable", "calamity", "disaster looms",
    "headed for disaster", "verge of collapse"
  )
)

message("Helpers loaded.")
