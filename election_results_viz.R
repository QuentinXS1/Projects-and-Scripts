# =============================================================================
# election_results_viz.R
# =============================================================================
# Publication-quality election data visualizations using ggplot2.
#
# Charts included:
#   1. Two-party vote share by district (stacked bar)
#   2. Voter turnout trend over multiple election cycles (line + ribbon)
#   3. Swing scatter plot: 2020 vs. 2024 DEM margin by precinct
#   4. Turnout by demographic quartile (box plot)
#   5. Registration growth by party (area chart)
#
# Author: Quentin Sprauve
# Dependencies: tidyverse, scales, ggrepel, patchwork
#
# Input files:
#   - district_results.csv  : district_id, district_name, election_year,
#                             dem_votes, rep_votes, total_votes
#   - precinct_results.csv  : precinct_id, district_name, dem_margin_2020,
#                             dem_margin_2024, total_votes_2024, county
#   - turnout_trend.csv     : district_name, election_year, election_type,
#                             turnout_rate
#   - registration.csv      : month_year, party, new_registrations
# =============================================================================

library(tidyverse)
library(scales)
library(ggrepel)     # non-overlapping labels
library(patchwork)   # combine multiple plots

# Shared theme for all charts
theme_political <- function(base_size = 12) {
  theme_minimal(base_size = base_size) +
    theme(
      plot.title       = element_text(face = "bold", size = base_size + 2),
      plot.subtitle    = element_text(color = "gray40", size = base_size - 1),
      plot.caption     = element_text(color = "gray50", size = base_size - 3, hjust = 0),
      axis.text        = element_text(color = "gray30"),
      legend.position  = "bottom",
      legend.title     = element_blank(),
      panel.grid.minor = element_blank()
    )
}

# Party color palette
PARTY_COLORS <- c("DEM" = "#2166ac", "REP" = "#d6604d", "IND" = "#4dac26")

output_dir <- "plots"
dir.create(output_dir, showWarnings = FALSE)


# =============================================================================
# Chart 1: Two-Party Vote Share by District (stacked bar)
# =============================================================================

plot_vote_share <- function(path = "district_results.csv") {
  df <- read_csv(path, show_col_types = FALSE) |>
    filter(election_year == max(election_year)) |>
    mutate(
      dem_pct = dem_votes / total_votes,
      rep_pct = rep_votes / total_votes,
      winner  = ifelse(dem_pct >= 0.5, "DEM", "REP"),
      district_name = fct_reorder(district_name, dem_pct)
    )

  df_long <- df |>
    select(district_name, winner, dem_pct, rep_pct) |>
    pivot_longer(cols = c(dem_pct, rep_pct), names_to = "party", values_to = "pct") |>
    mutate(party = recode(party, dem_pct = "DEM", rep_pct = "REP"))

  p <- ggplot(df_long, aes(x = district_name, y = pct, fill = party)) +
    geom_col(width = 0.7) +
    geom_hline(yintercept = 0.5, linetype = "dashed", color = "white", linewidth = 0.8) +
    scale_fill_manual(values = PARTY_COLORS) +
    scale_y_continuous(labels = percent_format(accuracy = 1), expand = c(0, 0)) +
    coord_flip() +
    labs(
      title    = "Two-Party Vote Share by District",
      subtitle = paste("General Election", max(df$election_year)),
      x        = NULL,
      y        = "Share of Two-Party Vote",
      caption  = "Source: Certified election results"
    ) +
    theme_political()

  ggsave(file.path(output_dir, "vote_share_by_district.png"), p, width = 9, height = 6, dpi = 150)
  message("Saved: vote_share_by_district.png")
  return(p)
}


# =============================================================================
# Chart 2: Turnout Trend Over Election Cycles (line + confidence ribbon)
# =============================================================================

plot_turnout_trend <- function(path = "turnout_trend.csv", districts = NULL) {
  df <- read_csv(path, show_col_types = FALSE) |>
    filter(election_type == "GENERAL")

  if (!is.null(districts)) {
    df <- filter(df, district_name %in% districts)
  }

  # Statewide average line
  avg <- df |>
    group_by(election_year) |>
    summarise(
      mean_turnout = mean(turnout_rate, na.rm = TRUE),
      sd_turnout   = sd(turnout_rate, na.rm = TRUE),
      .groups = "drop"
    )

  p <- ggplot() +
    # Confidence ribbon (±1 SD across districts)
    geom_ribbon(
      data = avg,
      aes(x = election_year, ymin = mean_turnout - sd_turnout,
          ymax = mean_turnout + sd_turnout),
      fill = "steelblue", alpha = 0.15
    ) +
    # Individual district lines
    geom_line(
      data = df,
      aes(x = election_year, y = turnout_rate, group = district_name),
      color = "gray70", linewidth = 0.6, alpha = 0.7
    ) +
    # Statewide average
    geom_line(
      data = avg,
      aes(x = election_year, y = mean_turnout),
      color = "#2166ac", linewidth = 1.4
    ) +
    geom_point(
      data = avg,
      aes(x = election_year, y = mean_turnout),
      color = "#2166ac", size = 3
    ) +
    scale_y_continuous(labels = percent_format(accuracy = 1), limits = c(0, 1)) +
    scale_x_continuous(breaks = unique(df$election_year)) +
    labs(
      title    = "Voter Turnout Trend — General Elections",
      subtitle = "Bold line = statewide average; ribbon = ±1 SD; gray = individual districts",
      x        = "Election Year",
      y        = "Turnout Rate",
      caption  = "Source: Precinct-level voter file"
    ) +
    theme_political()

  ggsave(file.path(output_dir, "turnout_trend.png"), p, width = 9, height = 5.5, dpi = 150)
  message("Saved: turnout_trend.png")
  return(p)
}


# =============================================================================
# Chart 3: Swing Scatter — 2020 vs. 2024 DEM Margin by Precinct
# =============================================================================

plot_swing_scatter <- function(path = "precinct_results.csv", label_n = 10) {
  df <- read_csv(path, show_col_types = FALSE) |>
    mutate(
      margin_shift = dem_margin_2024 - dem_margin_2020,
      flip_status  = case_when(
        dem_margin_2020 < 0 & dem_margin_2024 >= 0 ~ "Flipped DEM",
        dem_margin_2020 >= 0 & dem_margin_2024 < 0 ~ "Flipped REP",
        dem_margin_2024 >= 0                        ~ "Held DEM",
        TRUE                                        ~ "Held REP"
      ),
      flip_status = factor(flip_status,
                           levels = c("Flipped DEM", "Held DEM", "Held REP", "Flipped REP"))
    )

  # Label the biggest swings
  top_swings <- df |>
    arrange(desc(abs(margin_shift))) |>
    slice_head(n = label_n)

  p <- ggplot(df, aes(x = dem_margin_2020, y = dem_margin_2024, color = flip_status)) +
    # Reference lines
    geom_hline(yintercept = 0, linetype = "dashed", color = "gray60") +
    geom_vline(xintercept = 0, linetype = "dashed", color = "gray60") +
    geom_abline(slope = 1, intercept = 0, linetype = "dotted", color = "gray40") +
    # Points sized by total votes
    geom_point(aes(size = total_votes_2024), alpha = 0.55) +
    # Labels for biggest movers
    geom_label_repel(
      data = top_swings,
      aes(label = precinct_id),
      size = 2.8, max.overlaps = 15, show.legend = FALSE,
      box.padding = 0.3, segment.color = "gray50"
    ) +
    scale_color_manual(values = c(
      "Flipped DEM" = "#2166ac",
      "Held DEM"    = "#92c5de",
      "Held REP"    = "#f4a582",
      "Flipped REP" = "#d6604d"
    )) +
    scale_size_continuous(range = c(1, 6), labels = comma, name = "Total Votes (2024)") +
    scale_x_continuous(labels = \(x) paste0(ifelse(x >= 0, "+", ""), round(x * 100), "D")) +
    scale_y_continuous(labels = \(x) paste0(ifelse(x >= 0, "+", ""), round(x * 100), "D")) +
    labs(
      title    = "Precinct Swing: 2020 vs. 2024 Democratic Margin",
      subtitle = "Points above the dotted line shifted toward DEM; below shifted toward REP",
      x        = "2020 DEM Margin",
      y        = "2024 DEM Margin",
      color    = NULL,
      caption  = "Source: Certified election results. Dotted = no change line."
    ) +
    guides(size = guide_legend(override.aes = list(alpha = 0.6))) +
    theme_political()

  ggsave(file.path(output_dir, "precinct_swing_scatter.png"), p, width = 9, height = 7, dpi = 150)
  message("Saved: precinct_swing_scatter.png")
  return(p)
}


# =============================================================================
# Chart 4: Turnout by Demographic Quartile (box plot)
# =============================================================================

plot_turnout_by_quartile <- function(path = "precinct_results.csv",
                                     demo_col = "pct_college_plus",
                                     demo_label = "% College Educated") {
  df <- read_csv(path, show_col_types = FALSE) |>
    filter(!is.na(.data[[demo_col]]), !is.na(turnout_rate_2024)) |>
    mutate(
      quartile = ntile(.data[[demo_col]], 4),
      quartile = factor(quartile, labels = c("Q1 (Lowest)", "Q2", "Q3", "Q4 (Highest)"))
    )

  # Quartile ranges for x-axis labels
  q_ranges <- df |>
    group_by(quartile) |>
    summarise(
      lo = min(.data[[demo_col]], na.rm = TRUE),
      hi = max(.data[[demo_col]], na.rm = TRUE),
      .groups = "drop"
    ) |>
    mutate(label = sprintf("%s\n(%.0f%%–%.0f%%)", quartile, lo * 100, hi * 100))

  df <- df |> left_join(q_ranges |> select(quartile, label), by = "quartile")

  p <- ggplot(df, aes(x = label, y = turnout_rate_2024, fill = quartile)) +
    geom_boxplot(outlier.alpha = 0.3, outlier.size = 1, width = 0.55) +
    geom_jitter(width = 0.15, alpha = 0.2, size = 0.8, color = "gray40") +
    stat_summary(fun = mean, geom = "point", shape = 18, size = 3, color = "white") +
    scale_fill_brewer(palette = "Blues", direction = 1) +
    scale_y_continuous(labels = percent_format(accuracy = 1)) +
    labs(
      title    = sprintf("Voter Turnout by %s Quartile", demo_label),
      subtitle = "Box = IQR; diamond = mean; dots = individual precincts",
      x        = demo_label,
      y        = "2024 Turnout Rate",
      caption  = "Source: Precinct voter file joined with ACS 5-year estimates"
    ) +
    theme_political() +
    theme(legend.position = "none")

  fname <- paste0("turnout_by_", gsub("[^a-z0-9]", "_", tolower(demo_label)), "_quartile.png")
  ggsave(file.path(output_dir, fname), p, width = 8, height = 5.5, dpi = 150)
  message(sprintf("Saved: %s", fname))
  return(p)
}


# =============================================================================
# Chart 5: Registration Growth by Party (area chart)
# =============================================================================

plot_registration_growth <- function(path = "registration.csv") {
  df <- read_csv(path, show_col_types = FALSE) |>
    mutate(
      month_year = as.Date(month_year),
      party      = factor(party, levels = c("DEM", "REP", "IND"))
    ) |>
    arrange(party, month_year) |>
    group_by(party) |>
    mutate(cumulative = cumsum(new_registrations)) |>
    ungroup()

  # Rolling 3-month average for smoother monthly view
  df <- df |>
    group_by(party) |>
    mutate(rolling_3mo = zoo::rollmean(new_registrations, k = 3, fill = NA, align = "right")) |>
    ungroup()

  # Combine into a two-panel plot
  p_cumulative <- ggplot(df, aes(x = month_year, y = cumulative, fill = party)) +
    geom_area(alpha = 0.7, position = "identity") +
    scale_fill_manual(values = PARTY_COLORS) +
    scale_y_continuous(labels = comma) +
    scale_x_date(date_labels = "%b %Y", date_breaks = "6 months") +
    labs(title = "Cumulative Registrations by Party", x = NULL, y = "Cumulative Total") +
    theme_political() +
    theme(axis.text.x = element_text(angle = 30, hjust = 1))

  p_monthly <- ggplot(df |> filter(!is.na(rolling_3mo)),
                      aes(x = month_year, y = rolling_3mo, color = party)) +
    geom_line(linewidth = 1.1) +
    geom_point(size = 1.5, alpha = 0.7) +
    scale_color_manual(values = PARTY_COLORS) +
    scale_y_continuous(labels = comma) +
    scale_x_date(date_labels = "%b %Y", date_breaks = "6 months") +
    labs(
      title   = "New Registrations (3-Month Rolling Avg)",
      x       = NULL,
      y       = "Registrations / Month",
      caption = "Source: Voter registration file. Rolling average smooths month-to-month noise."
    ) +
    theme_political() +
    theme(axis.text.x = element_text(angle = 30, hjust = 1))

  combined <- p_cumulative / p_monthly +
    plot_annotation(
      title    = "Voter Registration Trends by Party",
      subtitle = "All election cycles",
      theme    = theme(plot.title = element_text(face = "bold", size = 14))
    )

  ggsave(file.path(output_dir, "registration_growth.png"), combined,
         width = 10, height = 9, dpi = 150)
  message("Saved: registration_growth.png")
  return(combined)
}


# =============================================================================
# Main — run all charts
# =============================================================================

main <- function() {
  message("Generating election visualizations...\n")

  # Uncomment each as you have the relevant data file:

  # plot_vote_share("district_results.csv")
  # plot_turnout_trend("turnout_trend.csv")
  # plot_swing_scatter("precinct_results.csv")
  # plot_turnout_by_quartile("precinct_results.csv", "pct_college_plus", "% College Educated")
  # plot_registration_growth("registration.csv")

  message("\nAll charts saved to /plots")
}

# main()
