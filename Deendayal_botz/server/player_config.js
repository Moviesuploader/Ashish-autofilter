/* Netflix-style player defaults. Backend/source URLs remain dynamic. */
window.MOVIEBOT_PLAYER_CONFIG = Object.freeze({
  speeds: [0.5, 0.75, 1, 1.25, 1.5, 1.75, 2],
  qualities: ["Auto", "1080p", "720p", "480p", "360p"],
  languages: ["Auto", "Hindi", "English", "Dual"],
  seekSeconds: 10,
  preload: "metadata",
  autoFailover: true
});
