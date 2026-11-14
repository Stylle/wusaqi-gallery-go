<script setup>
const props=defineProps({name:String});
const paths={
 "releases": "M5 3h14v18H5z M8 7h8 M8 11h8 M8 15h5",
 "devices": "M3 4h18v12H3z M8 20h8 M12 16v4",
 "notifications": "M18 8a6 6 0 0 0-12 0v5l-2 3h16l-2-3z M10 20h4",
 "logs": "M8 5h13 M8 12h13 M8 19h13 M3 5h.01 M3 12h.01 M3 19h.01",
 "members": "M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2 M22 21v-2a4 4 0 0 0-3-3.87 M16 3.13a4 4 0 0 1 0 7.75 M13 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0",
 "settings": "M4 6h16 M4 12h16 M4 18h16 M8 3v6 M16 9v6 M10 15v6",
 "account": "M12 3l8 4v6c0 4-5 7-8 9-3-2-8-5-8-9V7z M8 12l3 3 5-6",
 "system": "M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z",
 "connection": "M10 13a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-2 2 M14 11a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l2-2",
 "webhook": "M5 19L19 5 M7 5h12v12",
 "telegram": "M22 2L9 15 M22 2l-7 20-6-7-7-6z",
 "schedules": "M12 8v5l3 2 M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0",
 "messages": "M21 11a8 8 0 0 1-8 8H6l-4 3V7a5 5 0 0 1 5-5h6a8 8 0 0 1 8 9z M7 7h8 M7 11h6",
 "all": "M3 6h18 M3 12h18 M3 18h18",
 "files": "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z M14 2v6h6",
 "history": "M8 5h13 M8 12h13 M8 19h13 M3 5h.01 M3 12h.01 M3 19h.01"
};
</script>
<template><svg class="ui-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path :d="paths[props.name] || paths.settings" /></svg></template>

