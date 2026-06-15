# =============================================================================
# voter_turnout_model.R
# =============================================================================
# Predicts precinct-level voter turnout using demographic and geographic
# variables. Fits two models:
#   1. Linear regression (OLS) — continuous turnout rate as outcome
#   2. Logistic regression     — binary "high turnout" flag as outcome
#
# Also includes:
#   - Variance Inflation Factor (VIF) check for multicollinearity
#   - Cross-validation (5-fold) to assess out-of-sample performance
#   - Coefficient plot and actual vs. predicted diagnostic chart
#
# Author: Quentin Sprauve
# Dependencies: tidyverse, broom, car, caret
#
# Input columns expected in precinct_data.csv:
#   precinct_id, turnout_rate, pct_black_non_hisp, pct_hispanic,
#   pct_college_plus, median_household_income, pct_under_30,
#   pct_over_65, district_type, election_year
# =============================================================================

library(tidyverse)
library(broom)       # tidy model outputs
library(car)         # VIF
library(caret)       # cross-validation

set.seed(42)

# -----------------------------------------------------------------------------
# 1. Load & validate data
# -----------------------------------------------------------------------------

load_precinct_data <- function(path) {
  df <- read_csv(path, show_col_types = FALSE)

  required <- c(
    "precinct_id", "turnout_rate", "pct_black_non_hisp", "pct_hispanic",
    "pct_college_plus", "median_household_income", "pct_under_30",
    "pct_over_65", "election_year"
  )
  missing <- setdiff(required, names(df))
  if (length(missing) > 0) {
    stop(glue::glue("Missing columns: {paste(missing, collapse=', ')}"))
  }

  # Validate ranges
  if (any(df$turnout_rate < 0 | df$turnout_rate > 1, na.rm = TRUE)) {
    warning("turnout_rate should be between 0 and 1 — values outside this range detected.")
  }

  # Drop rows with any NA in modeling variables
  df_clean <- df |>
    drop_na(all_of(required)) |>
    filter(turnout_rate >= 0, turnout_rate <= 1)

  n_dropped <- nrow(df) - nrow(df_clean)
  if (n_dropped > 0) message(sprintf("Dropped %d rows with missing or invalid values.", n_dropped))

  message(sprintf("Loaded %d precincts for modeling.", nrow(df_clean)))
  return(df_clean)
}


# -----------------------------------------------------------------------------
# 2. Feature engineering
# -----------------------------------------------------------------------------

engineer_features <- function(df) {
  df |>
    mutate(
      # Income scaled to $10k units for interpretable coefficients
      income_10k        = median_household_income / 10000,

      # Binary outcome: "high turnout" = above 60%
      high_turnout      = as.factor(ifelse(turnout_rate >= 0.60, 1, 0)),

      # Senior-to-youth ratio (higher = older electorate = higher turnout)
      senior_youth_ratio = pct_over_65 / (pct_under_30 + 0.001),

      # Election year as factor for fixed effects
      year_factor       = as.factor(election_year)
    )
}


# -----------------------------------------------------------------------------
# 3. OLS regression — continuous turnout rate
# -----------------------------------------------------------------------------

fit_ols <- function(df) {
  formula <- turnout_rate ~
    pct_black_non_hisp +
    pct_hispanic +
    pct_college_plus +
    income_10k +
    pct_under_30 +
    pct_over_65 +
    senior_youth_ratio +
    year_factor

  model <- lm(formula, data = df)

  message("\n--- OLS Model Summary ---")
  print(summary(model))

  # VIF check (values > 5 suggest problematic multicollinearity)
  message("\n--- Variance Inflation Factors ---")
  vif_vals <- vif(model)
  print(round(vif_vals, 2))
  flagged <- names(vif_vals[vif_vals > 5])
  if (length(flagged) > 0) {
    warning(sprintf("High VIF (>5) detected: %s. Consider removing or combining.", paste(flagged, collapse = ", ")))
  }

  return(model)
}


# -----------------------------------------------------------------------------
# 4. Logistic regression — binary high-turnout outcome
# -----------------------------------------------------------------------------

fit_logistic <- function(df) {
  formula <- high_turnout ~
    pct_black_non_hisp +
    pct_hispanic +
    pct_college_plus +
    income_10k +
    pct_under_30 +
    pct_over_65 +
    year_factor

  model <- glm(formula, data = df, family = binomial(link = "logit"))

  message("\n--- Logistic Model Summary ---")
  print(summary(model))

  # Odds ratios with 95% CI
  message("\n--- Odds Ratios (95% CI) ---")
  or_table <- tidy(model, exponentiate = TRUE, conf.int = TRUE) |>
    select(term, estimate, conf.low, conf.high, p.value) |>
    rename(odds_ratio = estimate) |>
    mutate(across(where(is.numeric), \(x) round(x, 4)))
  print(or_table)

  return(model)
}


# -----------------------------------------------------------------------------
# 5. Cross-validation (5-fold)
# -----------------------------------------------------------------------------

cross_validate_ols <- function(df) {
  ctrl <- trainControl(method = "cv", number = 5)

  cv_model <- train(
    turnout_rate ~
      pct_black_non_hisp + pct_hispanic + pct_college_plus +
      income_10k + pct_under_30 + pct_over_65 + senior_youth_ratio + year_factor,
    data      = df,
    method    = "lm",
    trControl = ctrl
  )

  message("\n--- 5-Fold Cross-Validation Results (OLS) ---")
  message(sprintf("  RMSE  : %.4f", cv_model$results$RMSE))
  message(sprintf("  R²    : %.4f", cv_model$results$Rsquared))
  message(sprintf("  MAE   : %.4f", cv_model$results$MAE))

  return(cv_model)
}


# -----------------------------------------------------------------------------
# 6. Diagnostic plots
# -----------------------------------------------------------------------------

plot_coefficient <- function(model, output_path = "plots/ols_coefficients.png") {
  coef_df <- tidy(model, conf.int = TRUE) |>
    filter(term != "(Intercept)", !str_starts(term, "year_factor")) |>
    mutate(
      term = recode(term,
        pct_black_non_hisp  = "% Black (non-Hispanic)",
        pct_hispanic        = "% Hispanic",
        pct_college_plus    = "% College Educated",
        income_10k          = "Median Income ($10k)",
        pct_under_30        = "% Under 30",
        pct_over_65         = "% Over 65",
        senior_youth_ratio  = "Senior-to-Youth Ratio"
      ),
      significant = p.value < 0.05
    )

  p <- ggplot(coef_df, aes(x = estimate, y = reorder(term, estimate), color = significant)) +
    geom_vline(xintercept = 0, linetype = "dashed", color = "gray50") +
    geom_errorbarh(aes(xmin = conf.low, xmax = conf.high), height = 0.2, linewidth = 0.8) +
    geom_point(size = 3) +
    scale_color_manual(
      values = c("TRUE" = "#2166ac", "FALSE" = "#b2b2b2"),
      labels = c("TRUE" = "p < 0.05", "FALSE" = "p ≥ 0.05"),
      name   = NULL
    ) +
    labs(
      title    = "OLS Regression: Predictors of Voter Turnout",
      subtitle = "Coefficient estimates with 95% confidence intervals",
      x        = "Coefficient (effect on turnout rate)",
      y        = NULL,
      caption  = "Source: Precinct-level voter file and ACS demographic data"
    ) +
    theme_minimal(base_size = 12) +
    theme(
      plot.title    = element_text(face = "bold"),
      legend.position = "bottom"
    )

  dir.create(dirname(output_path), showWarnings = FALSE, recursive = TRUE)
  ggsave(output_path, plot = p, width = 8, height = 5, dpi = 150)
  message(sprintf("Coefficient plot saved to %s", output_path))
  return(p)
}


plot_actual_vs_predicted <- function(model, df, output_path = "plots/ols_actual_vs_predicted.png") {
  df_plot <- df |>
    mutate(
      predicted = predict(model, newdata = df),
      residual  = turnout_rate - predicted
    )

  rmse <- sqrt(mean(df_plot$residual^2))

  p <- ggplot(df_plot, aes(x = predicted, y = turnout_rate)) +
    geom_point(alpha = 0.4, color = "#2166ac", size = 1.5) +
    geom_abline(slope = 1, intercept = 0, color = "firebrick", linetype = "dashed") +
    annotate("text", x = Inf, y = -Inf, hjust = 1.1, vjust = -0.5,
             label = sprintf("RMSE = %.3f", rmse), size = 3.5, color = "gray30") +
    labs(
      title    = "Actual vs. Predicted Voter Turnout",
      subtitle = "OLS model — dashed line = perfect prediction",
      x        = "Predicted Turnout Rate",
      y        = "Actual Turnout Rate",
      caption  = "Source: Precinct-level voter file and ACS demographic data"
    ) +
    scale_x_continuous(labels = scales::percent) +
    scale_y_continuous(labels = scales::percent) +
    theme_minimal(base_size = 12) +
    theme(plot.title = element_text(face = "bold"))

  dir.create(dirname(output_path), showWarnings = FALSE, recursive = TRUE)
  ggsave(output_path, plot = p, width = 7, height = 6, dpi = 150)
  message(sprintf("Actual vs. predicted plot saved to %s", output_path))
  return(p)
}


# -----------------------------------------------------------------------------
# 7. Export tidy model results
# -----------------------------------------------------------------------------

export_model_results <- function(ols_model, logit_model, output_dir = "model-output") {
  dir.create(output_dir, showWarnings = FALSE)

  # OLS coefficients
  tidy(ols_model, conf.int = TRUE) |>
    mutate(across(where(is.numeric), \(x) round(x, 6))) |>
    write_csv(file.path(output_dir, "ols_coefficients.csv"))

  # Logistic odds ratios
  tidy(logit_model, exponentiate = TRUE, conf.int = TRUE) |>
    mutate(across(where(is.numeric), \(x) round(x, 6))) |>
    write_csv(file.path(output_dir, "logistic_odds_ratios.csv"))

  message(sprintf("Model results exported to %s/", output_dir))
}


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

main <- function(data_path = "precinct_data.csv") {
  df_raw  <- load_precinct_data(data_path)
  df      <- engineer_features(df_raw)

  ols_model   <- fit_ols(df)
  logit_model <- fit_logistic(df)

  cross_validate_ols(df)

  plot_coefficient(ols_model)
  plot_actual_vs_predicted(ols_model, df)

  export_model_results(ols_model, logit_model)

  message("\nDone.")
}

# Uncomment to run:
# main("precinct_data.csv")
