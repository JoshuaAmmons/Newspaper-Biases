# 03b — Newspaper -> geography crosswalk from parsed titles + corpus state column.
# In : data_panels/newspaper_geo_raw.csv  (produced by python/extract_newspaper_geo.py)
# Out: data_panels/xwalk_lccn_county.parquet -> lccn, newspaper_name, city, county_title, state, region
#
# State is solid (~97%; the title parse and the corpus `state` column corroborate, modulo
# code-vs-fullname format). `county_title` is only the ~6.6% of titles that name a county/parish.
# FULL county-FIPS assignment is DEFERRED to the NHGIS historical-county step (08): county
# boundaries shift across 1895-1945 and the shocks are defined on NHGIS counties, so the
# newspaper->county map must use that same time-varying framework, not a modern gazetteer.
suppressMessages({ library(data.table); library(arrow) })
DATA <- Sys.getenv("CAPLAN_DATA", "C:/Users/jdamm/Caplan")
raw <- fread(file.path(DATA, "data_panels", "newspaper_geo_raw.csv"),
             encoding = "UTF-8", colClasses = "character", na.strings = NULL)
for (col in c("lccn", "newspaper_name", "city", "county_title", "state_title", "state_corpus")) {
  if (col %in% names(raw)) raw[is.na(get(col)), (col) := ""]
}

# Full state name -> USPS code (50 states + DC). The corpus column already resolves historical
# territories to modern states (e.g. "W.T." titles carry state_corpus = "Washington").
name2code <- setNames(state.abb, state.name); name2code["District of Columbia"] <- "DC"
raw[, scc := name2code[state_corpus]]
raw[, state := fifelse(state_title != "", state_title, fifelse(is.na(scc), "", scc))]

# Census region from state code (for stage-04 stratification; falls back to "Unknown").
code2region <- setNames(as.character(state.region), state.abb); code2region["DC"] <- "South"
raw[, region := code2region[state]]; raw[is.na(region), region := "Unknown"]

# One row per LCCN: keep the title variant carrying the most geography.
raw[, gs := (city != "") + (county_title != "") + (state != "")]
setorder(raw, lccn, -gs)
xwalk <- raw[lccn != "", .SD[1L], by = lccn,
             .SDcols = c("newspaper_name", "city", "county_title", "state", "region", "state_corpus")]

n <- nrow(xwalk)
cat(sprintf("lccns                 : %d\n", n))
cat(sprintf("with state            : %.1f%%\n", 100 * mean(xwalk$state != "")))
cat(sprintf("with census region    : %.1f%%\n", 100 * mean(xwalk$region != "Unknown")))
cat(sprintf("county named in title : %.1f%%\n", 100 * mean(xwalk$county_title != "")))
cat("state distribution (top 10):\n")
print(head(sort(table(xwalk$state[xwalk$state != ""]), decreasing = TRUE), 10))
write_parquet(xwalk, file.path(DATA, "data_panels", "xwalk_lccn_county.parquet"))
cat("wrote data_panels/xwalk_lccn_county.parquet\n")
