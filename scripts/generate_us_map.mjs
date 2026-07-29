/**
 * Generates the inline US map SVG used by the landing page's live activity map.
 *
 * Source data: us-atlas (https://github.com/topojson/us-atlas), derived from the
 * US Census Bureau's cartographic boundary files, which are public domain as a
 * work of the US federal government.
 *
 * Run with: npm run build:map
 *
 * Output is committed to the repo, so this script is only needed when the map
 * geometry or viewBox needs to change — there is no runtime dependency on it.
 */
import { writeFileSync } from "node:fs";
import { createRequire } from "node:module";

import { geoAlbersUsa, geoPath } from "d3-geo";
import { feature } from "topojson-client";
import { presimplify, simplify } from "topojson-simplify";

const require = createRequire(import.meta.url);
const topology = require("us-atlas/states-10m.json");

const WIDTH = 1000;
const HEIGHT = 600;
const PRECISION = 1;
// Drops small coastline/border detail that is invisible at this render size.
// Raise to shrink the output further, lower for a more faithful outline.
const SIMPLIFY_WEIGHT = 0.05;

// FIPS code -> USPS state code. The `uf` column in `licitacoes` stores USPS
// codes (from SAM.gov's placeOfPerformance.state.code), so the rendered paths
// are keyed the same way to let the front-end line dots up with states.
const FIPS_TO_USPS = {
  "01": "AL", "02": "AK", "04": "AZ", "05": "AR", "06": "CA", "08": "CO",
  "09": "CT", "10": "DE", "11": "DC", "12": "FL", "13": "GA", "15": "HI",
  "16": "ID", "17": "IL", "18": "IN", "19": "IA", "20": "KS", "21": "KY",
  "22": "LA", "23": "ME", "24": "MD", "25": "MA", "26": "MI", "27": "MN",
  "28": "MS", "29": "MO", "30": "MT", "31": "NE", "32": "NV", "33": "NH",
  "34": "NJ", "35": "NM", "36": "NY", "37": "NC", "38": "ND", "39": "OH",
  "40": "OK", "41": "OR", "42": "PA", "44": "RI", "45": "SC", "46": "SD",
  "47": "TN", "48": "TX", "49": "UT", "50": "VT", "51": "VA", "53": "WA",
  "54": "WV", "55": "WI", "56": "WY",
};

const simplified = simplify(presimplify(topology), SIMPLIFY_WEIGHT);

const states = feature(simplified, simplified.objects.states).features
  // geoAlbersUsa covers the 50 states + DC only; territories project to null.
  .filter((f) => FIPS_TO_USPS[f.id])
  .sort((a, b) => FIPS_TO_USPS[a.id].localeCompare(FIPS_TO_USPS[b.id]));

// Inset the projection so Alaska and Hawaii (which Albers USA places along the
// bottom edge) keep a little breathing room instead of sitting flush against it.
const MARGIN = 12;
const projection = geoAlbersUsa().fitExtent(
  [
    [MARGIN, MARGIN],
    [WIDTH - MARGIN, HEIGHT - MARGIN],
  ],
  { type: "FeatureCollection", features: states }
);
const path = geoPath(projection);

// Round coordinates down to one decimal place — at this viewBox size the
// difference is sub-pixel, and it cuts the generated path data roughly in half.
const round = (d) => d.replace(/-?\d+\.\d+/g, (n) => (+n).toFixed(PRECISION));

// Simplification collapses tiny islands (Alaska has hundreds) into subpaths
// whose points are all the same rounded coordinate. They render as nothing, so
// drop any subpath that no longer has at least 3 distinct points.
function dropDegenerateSubpaths(d) {
  return d
    .split("M")
    .filter(Boolean)
    .map((sub) => "M" + sub)
    .filter((sub) => new Set(sub.match(/-?[\d.]+,-?[\d.]+/g) ?? []).size >= 3)
    .join("");
}

const clean = (d) => dropDegenerateSubpaths(round(d));

const paths = [];

for (const state of states) {
  const usps = FIPS_TO_USPS[state.id];
  const d = path(state);
  if (!d) continue;

  // The <title> doubles as the accessible name and as the front-end's only
  // source for the state's display label.
  paths.push(
    `<path class="us-state" data-state="${usps}" d="${clean(d)}">` +
      `<title>${state.properties.name}</title></path>`
  );
}

const svgPartial = `{# GENERATED FILE — do not edit by hand.
   Regenerate with: npm run build:map  (see scripts/generate_us_map.mjs)
   Geometry from us-atlas / US Census cartographic boundary files (public domain). #}
<g id="us-map-states">
${paths.join("\n")}
</g>
`;

writeFileSync("web/templates/partials/_us_map_states.html", svgPartial);

console.log(
  `Wrote ${states.length} state paths ` +
    `(${(svgPartial.length / 1024).toFixed(1)} KB) ` +
    `for a ${WIDTH}x${HEIGHT} viewBox.`
);
