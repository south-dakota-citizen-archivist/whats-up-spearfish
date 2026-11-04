// Photo gallery: thumbnails that open one big photo at a time in a dialog, with
// previous/next buttons, arrow keys and swipes. Each thumbnail is a link to the
// full photo, so it still works without JavaScript.
//
// Optionally filtered: photos carry a `kind`, and setFilter(kind) shows only those
// (?species=… in the address picks one on arrival). The grid shows the first
// data-limit (data-limit-lg on large screens) matches, with a "show more" button;
// the dialog steps through every match.
//
//   <div x-data="photoGallery()" data-limit="6" data-limit-lg="12">
//     <script type="application/json" x-ref="photos">[{full, kind, …}]</script>
//     <li x-show="shows(0)"><a href="…" @click.prevent="show(0)">…</a></li>
//     <dialog x-ref="dialog" @close="closed()">…</dialog>
//   </div>
document.addEventListener("alpine:init", () => {
  Alpine.data("photoGallery", () => ({
    photos: [],
    i: null,
    filter: "",
    expanded: false,
    limit: Infinity,
    startX: null,

    init() {
      this.photos = JSON.parse(this.$refs.photos.textContent);
      const large = window.matchMedia("(min-width: 1024px)").matches;
      const limit = Number((large && this.$el.dataset.limitLg) || this.$el.dataset.limit);
      if (limit) this.limit = limit;
      const wanted = new URLSearchParams(location.search).get("species");
      if (wanted && this.photos.some((p) => p.kind === wanted)) this.filter = wanted;
    },
    get photo() {
      return this.i === null ? null : this.photos[this.i];
    },
    // the photos the filter lets through, as indexes into photos
    get matching() {
      return this.photos.map((p, n) => n).filter((n) => !this.filter || this.photos[n].kind === this.filter);
    },
    shows(n) {
      const at = this.matching.indexOf(n);
      return at !== -1 && (this.expanded || at < this.limit);
    },
    get hiddenCount() {
      return this.expanded ? 0 : Math.max(0, this.matching.length - this.limit);
    },
    setFilter(kind) {
      this.filter = this.filter === kind ? "" : kind;
      this.expanded = false;
    },
    show(n) {
      this.i = n;
      if (!this.$refs.dialog.open) this.$refs.dialog.showModal();
    },
    // where the open photo is among the matches ("3 of 12")
    get position() {
      return this.matching.indexOf(this.i) + 1;
    },
    step(by) {
      if (this.i === null) return;
      const list = this.matching;
      const at = list.indexOf(this.i);
      this.i = list[(at + by + list.length) % list.length];
      // fetch the next one ahead so stepping through feels instant
      const ahead = this.photos[list[(at + 2 * by + 2 * list.length) % list.length]];
      if (ahead) new Image().src = ahead.full;
    },
    close() {
      this.$refs.dialog.close();
    },
    closed() {
      this.i = null;
    },
    touchStart(e) {
      this.startX = e.changedTouches[0].clientX;
    },
    touchEnd(e) {
      if (this.startX === null) return;
      const dx = e.changedTouches[0].clientX - this.startX;
      this.startX = null;
      if (Math.abs(dx) > 50) this.step(dx < 0 ? 1 : -1);
    },
  }));
});
