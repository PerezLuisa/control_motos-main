// Registro: si se elige "Administrador", pide la clave del super admin en una ventana
// antes de enviar. El servidor vuelve a verificarla (esta ventana es solo la interfaz).
;(() => {
  const form = document.getElementById('form-registro')
  const modal = document.getElementById('modal-superadmin')
  if (!form || !modal) return

  const oculto = document.getElementById('clave_superadmin')
  const entrada = document.getElementById('clave-superadmin-modal')
  const error = document.getElementById('error-superadmin')
  const verificar = document.getElementById('verificar-superadmin')

  const rolElegido = () => form.querySelector('input[name="rol"]:checked')?.value

  function mostrarError(texto) {
    error.textContent = texto
    error.hidden = !texto
  }

  form.addEventListener('submit', (e) => {
    if (rolElegido() !== 'admin' || oculto.value) return
    e.preventDefault()
    mostrarError('')
    entrada.value = ''
    modal.showModal()
    entrada.focus()
  })

  // Si cambia a "Empleado", se descarta la clave ya verificada
  form.querySelectorAll('input[name="rol"]').forEach((r) => r.addEventListener('change', () => (oculto.value = '')))

  document.getElementById('cancelar-superadmin').addEventListener('click', () => modal.close())

  document.getElementById('form-superadmin').addEventListener('submit', async (e) => {
    e.preventDefault()
    const clave = entrada.value
    if (!clave) return
    verificar.disabled = true
    try {
      const { ok, datos } = await api('/api/registro/superadmin', { method: 'POST', body: JSON.stringify({ clave }) })
      if (!ok) {
        mostrarError(datos.mensaje || 'Contraseña del super administrador incorrecta.')
        entrada.select()
        return
      }
      oculto.value = clave
      modal.close()
      form.requestSubmit()
    } catch (_) {
      mostrarError('No se pudo verificar. Revise la conexión e intente de nuevo.')
    } finally {
      verificar.disabled = false
    }
  })
})()
