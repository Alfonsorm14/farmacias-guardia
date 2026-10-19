package es.alfonsorivero.farmacias_guardia

import android.content.Intent
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

class MainActivity : FlutterActivity() {
    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        // Compartir texto con el selector del sistema (WhatsApp, SMS, correo...), sin dependencias.
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "es.alfonsorivero.farmacias_guardia/compartir")
            .setMethodCallHandler { call, result ->
                if (call.method == "texto") {
                    val texto = call.argument<String>("texto") ?: ""
                    val envio = Intent(Intent.ACTION_SEND).apply {
                        type = "text/plain"
                        putExtra(Intent.EXTRA_TEXT, texto)
                    }
                    startActivity(Intent.createChooser(envio, "Compartir farmacia de guardia"))
                    result.success(true)
                } else {
                    result.notImplemented()
                }
            }
    }
}
