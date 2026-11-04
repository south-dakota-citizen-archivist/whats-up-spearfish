// Photo gallery: thumbnails that open one big photo at a time in a dialog, with
// previous/next buttons, arrow keys and swipes. Each thumbnail is a link to the
// full photo, so it still works without JavaScript.
//
//   <div x-data="photoGallery()">
//     <script type="application/json" x-ref="photos">[{full, caption, …}]</script>
//     <a href="…" @click.prevent="show(0)">…</a>
//     <dialog x-ref="dialog" @close="closed()">…</dialog>
//   </div>
document.addEventListener("alpine:init", () => {
  Alpine.data("photoGallery", () => ({
    photos: [],
    i: null,
    startX: null,

    init() {
      this.photos = JSON.parse(this.$refs.photos.textContent);
    },
    get photo() {
      return this.i === null ? null : this.photos[this.i];
    },
    show(n) {
      this.i = n;
      if (!this.$refs.dialog.open) this.$refs.dialog.showModal();
    },
    step(by) {
      if (this.i === null) return;
      this.i = (this.i + by + this.photos.length) % this.photos.length;
      // fetch the next one ahead so stepping through feels instant
      const ahead = this.photos[(this.i + by + this.photos.length) % this.photos.length];
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
