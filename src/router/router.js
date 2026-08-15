import { createRouter, createWebHistory } from 'vue-router'
import ChatPage from './../components/chat/ChatPage.vue'
import ItemsPage from './../components/items/ItemsPage.vue'
import ItemDetailPage from './../components/items/ItemDetailPage.vue'

const routes = [
  { path: '/', redirect: { name: 'chat' } },
  { path: '/chat', name: 'chat', component: ChatPage },
  { path: '/items', name: 'items', component: ItemsPage },
  { path: '/itemdetail', name: 'itemdetail', component: ItemDetailPage },
  { path: '/:catchAll(.*)', redirect: { name: 'chat' } },
]

export default createRouter({
  history: createWebHistory(),
  routes,
})
