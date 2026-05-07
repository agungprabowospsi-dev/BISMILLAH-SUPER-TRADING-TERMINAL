export default {
  content: ['./index.html','./src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        bg: { primary:'#f1f5f9', secondary:'#e2e8f0', card:'#ffffff', elevated:'#f8fafc' },
        accent: { green:'#16a34a', red:'#dc2626', gold:'#d97706', blue:'#0ea5e9', purple:'#7c3aed' },
        border: { dim:'#e2e8f0', bright:'#cbd5e1' }
      },
      fontFamily: {
        mono: ['JetBrains Mono','monospace'],
        display: ['Rajdhani','sans-serif'],
        body: ['DM Sans','sans-serif']
      }
    }
  },
  plugins: []
}
