<script setup>
import { ref, watch, onMounted, onUnmounted } from 'vue'
import Gallery from './views/Gallery.vue'
import Random from './views/Random.vue'
import Upload from './views/Upload.vue'
import ApiDoc from './views/ApiDoc.vue'
import About from './views/About.vue'

const views = { gallery: Gallery, random: Random, upload: Upload, api: ApiDoc, about: About }
const route = ref('gallery')

function sync() {
  const h = location.hash.replace(/^#\/?/, '') || 'gallery'
  route.value = views[h] ? h : 'gallery'
}
onMounted(() => { sync(); window.addEventListener('hashchange', sync) })
onUnmounted(() => window.removeEventListener('hashchange', sync))
</script>

<template>
  <header class="topbar">
    <span class="logo">lolis-gallery</span>
    <nav>
      <a href="#/gallery" :class="{ active: route === 'gallery' }">Gallery</a>
      <a href="#/random" :class="{ active: route === 'random' }">Random</a>
      <a href="#/upload" :class="{ active: route === 'upload' }">Upload</a>
      <a href="#/api" :class="{ active: route === 'api' }">API</a>
      <a href="#/about" :class="{ active: route === 'about' }">About</a>
    </nav>
  </header>
  <main class="wrap">
    <component :is="views[route]" />
  </main>
</template>
