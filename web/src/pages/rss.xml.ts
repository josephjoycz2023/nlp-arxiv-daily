import rss from "@astrojs/rss";
import type { APIContext } from "astro";
import { getDashboardData } from "../utils/personalizedDashboard.ts";

export async function GET(context: APIContext) {
  const dashboard = getDashboardData();
  const digestColumn = dashboard.columns.find((column) => column.id === "digest");
  const l2Column = dashboard.columns.find((column) => column.id === "l2");
  const papers = [
    ...(digestColumn?.groups.flatMap((group) => group.papers) ?? []),
    ...(l2Column?.groups.flatMap((group) => group.papers) ?? []),
  ];

  const items = papers.map((paper) => ({
    title: paper.title,
    link: paper.paperUrl ?? paper.pdfUrl ?? new URL(import.meta.env.BASE_URL, context.site!).toString(),
    pubDate: paper.publishedDate ? new Date(paper.publishedDate) : new Date(`${dashboard.selectedDate}T00:00:00Z`),
    description:
      paper.summary ??
      paper.whyRelevant ??
      `${paper.primaryDirection.label} · pool ${dashboard.selectedDate}`,
    customData: `<category>${paper.primaryDirection.label}</category>`,
  }));

  const homeUrl = new URL(import.meta.env.BASE_URL, context.site!).toString();

  return rss({
    title: "Personalized Research Dashboard",
    description: `Latest digest and L2 papers from pool ${dashboard.selectedDate}.`,
    site: homeUrl,
    items,
  });
}
