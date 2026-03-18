<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="32" height="32">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#2e6da4"/>
      <stop offset="100%" stop-color="#1a4368"/>
    </linearGradient>
  </defs>

  <!-- Fond rond -->
  <circle cx="16" cy="16" r="15.5" fill="url(#bg)"/>

  <!-- Nuage stylisé, gras, blanc -->
  <!-- Corps principal du nuage -->
  <ellipse cx="16" cy="18" rx="9.5" ry="5.5" fill="white"/>
  <!-- Bosse gauche -->
  <circle cx="10" cy="15.5" r="4.5" fill="white"/>
  <!-- Bosse centrale haute -->
  <circle cx="16" cy="13" r="5.5" fill="white"/>
  <!-- Bosse droite -->
  <circle cx="22" cy="15.5" r="4" fill="white"/>

  <!-- Trait vert dessous = données / raster -->
  <rect x="4" y="22" width="24" height="3.5" rx="1.75" fill="#afcb37"/>

  <!-- 3 petits traits blancs dans le vert = grille raster -->
  <rect x="9.5" y="22" width="1" height="3.5" fill="white" opacity="0.4"/>
  <rect x="15.5" y="22" width="1" height="3.5" fill="white" opacity="0.4"/>
  <rect x="21.5" y="22" width="1" height="3.5" fill="white" opacity="0.4"/>
</svg>
