(function () {
  try {
    var stored = window.localStorage.getItem("fortexahome-theme");
    document.documentElement.dataset.theme = stored === "escuro" ? "escuro" : "minimal";
  } catch (error) {
    document.documentElement.dataset.theme = "minimal";
  }
})();
