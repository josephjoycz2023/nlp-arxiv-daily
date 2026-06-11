import { OGImageRoute } from "astro-og-canvas";
import { getAvailablePoolDates, getDashboardData } from "../../utils/personalizedDashboard.ts";

interface OgPage {
  title: string;
  description: string;
}

const latestDashboard = getDashboardData();
const pages: Record<string, OgPage> = {
  index: {
    title: "Personalized Research Dashboard",
    description: `Pool ${latestDashboard.selectedDate} · Digest ${latestDashboard.stats.digestMustRead}`,
  },
  archive: {
    title: "Pool Date Archive",
    description: "Browse personalized snapshots by pool date.",
  },
};

for (const date of getAvailablePoolDates()) {
  const dashboard = getDashboardData(date);
  pages[`archive/${date}`] = {
    title: `Pool ${date}`,
    description: `${dashboard.stats.poolCount} papers · L2 ${dashboard.stats.l2Count} · Digest ${dashboard.stats.digestMustRead}`,
  };
}

export const prerender = true;

export const { getStaticPaths, GET } = await OGImageRoute({
  param: "slug",
  pages,
  getSlug: (path) => path,
  getImageOptions: (_path, page: OgPage) => ({
    title: page.title,
    description: page.description,
    bgGradient: [
      [245, 236, 223],
      [250, 247, 242],
    ],
    border: { color: [190, 96, 53], width: 8, side: "block-start" },
    padding: 80,
    font: {
      title: { size: 76, weight: "Bold", color: [44, 38, 35], lineHeight: 1.15 },
      description: { size: 34, color: [102, 92, 86], lineHeight: 1.35 },
    },
  }),
});
