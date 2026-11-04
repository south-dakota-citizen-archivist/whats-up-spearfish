// Long lists (marked data-more="N") show their first N items and a "Show more" button,
// instead of scrolling inside their card, which feels like a trap on a phone.
// data-more-lg="M" sets a different count for large screens (a photo grid shows more
// per row there); data-more-noun names what's hidden ("days"). Without JavaScript every
// item simply shows.
document.addEventListener("DOMContentLoaded", () => {
  const large = window.matchMedia("(min-width: 1024px)").matches;
  for (const list of document.querySelectorAll("[data-more]")) {
    const limit = Number((large && list.dataset.moreLg) || list.dataset.more) || 8;
    // items hidden for another reason (a meeting that's moved to the other list) don't count
    const extra = [...list.children].filter((el) => !el.classList.contains("hidden")).slice(limit);
    if (extra.length < 3) continue; // not worth a button for one or two more
    const noun = list.dataset.moreNoun ? ` ${list.dataset.moreNoun}` : ""; // "Show 6 more days"
    const label = `Show ${extra.length} more${noun}`;
    const button = document.createElement("button");
    button.type = "button";
    button.className =
      "mt-3 w-full py-2 border border-stone-300 bg-white text-sm font-semibold text-pine-700 hover:border-pine-600";
    button.textContent = label;
    button.setAttribute("aria-expanded", "false");
    const show = (open) => {
      for (const item of extra) item.hidden = !open;
      button.setAttribute("aria-expanded", String(open));
      button.textContent = open ? "Show fewer" : label;
    };
    button.addEventListener("click", () => {
      const open = button.getAttribute("aria-expanded") !== "true";
      show(open);
      // keyboard users continue from the first newly shown item
      if (open) extra[0].querySelector("a, button")?.focus();
    });
    show(false);
    list.after(button);
  }
});
