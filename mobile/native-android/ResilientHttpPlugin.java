package net.pu2bru.qsomanager;

import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

import java.io.IOException;
import java.net.InetAddress;
import java.net.UnknownHostException;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Iterator;
import java.util.List;
import java.util.Locale;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

import okhttp3.Call;
import okhttp3.Callback;
import okhttp3.Dns;
import okhttp3.Headers;
import okhttp3.HttpUrl;
import okhttp3.MediaType;
import okhttp3.OkHttpClient;
import okhttp3.Request;
import okhttp3.RequestBody;
import okhttp3.Response;
import okhttp3.ResponseBody;
import okhttp3.dnsoverhttps.DnsOverHttps;

@CapacitorPlugin(name = "ResilientHttp")
public class ResilientHttpPlugin extends Plugin {
    private OkHttpClient client;
    private final AtomicReference<String> lastDnsMode = new AtomicReference<>("not-used");

    @Override
    public void load() {
        OkHttpClient bootstrap = new OkHttpClient.Builder()
            .connectTimeout(15, TimeUnit.SECONDS)
            .readTimeout(30, TimeUnit.SECONDS)
            .build();

        Dns google = new DnsOverHttps.Builder()
            .client(bootstrap)
            .url(HttpUrl.get("https://dns.google/dns-query"))
            .bootstrapDnsHosts(
                literal("8.8.8.8"),
                literal("8.8.4.4")
            )
            .includeIPv6(true)
            .build();

        Dns cloudflare = new DnsOverHttps.Builder()
            .client(bootstrap)
            .url(HttpUrl.get("https://cloudflare-dns.com/dns-query"))
            .bootstrapDnsHosts(
                literal("1.1.1.1"),
                literal("1.0.0.1")
            )
            .includeIPv6(true)
            .build();

        Dns resilientDns = hostname -> {
            List<Throwable> failures = new ArrayList<>();
            try {
                List<InetAddress> addresses = Dns.SYSTEM.lookup(hostname);
                if (!addresses.isEmpty()) {
                    lastDnsMode.set("android-system");
                    return addresses;
                }
            } catch (Throwable e) {
                failures.add(e);
            }

            try {
                List<InetAddress> addresses = google.lookup(hostname);
                if (!addresses.isEmpty()) {
                    lastDnsMode.set("google-doh");
                    return addresses;
                }
            } catch (Throwable e) {
                failures.add(e);
            }

            try {
                List<InetAddress> addresses = cloudflare.lookup(hostname);
                if (!addresses.isEmpty()) {
                    lastDnsMode.set("cloudflare-doh");
                    return addresses;
                }
            } catch (Throwable e) {
                failures.add(e);
            }

            UnknownHostException failure = new UnknownHostException(
                "QSO Manager could not resolve " + hostname + " using Android DNS, Google DoH or Cloudflare DoH"
            );
            for (Throwable e : failures) failure.addSuppressed(e);
            throw failure;
        };

        client = bootstrap.newBuilder()
            .dns(resilientDns)
            .connectTimeout(20, TimeUnit.SECONDS)
            .readTimeout(60, TimeUnit.SECONDS)
            .writeTimeout(60, TimeUnit.SECONDS)
            .retryOnConnectionFailure(true)
            .build();
    }

    private static InetAddress literal(String ip) {
        try {
            return InetAddress.getByName(ip);
        } catch (UnknownHostException impossible) {
            throw new IllegalArgumentException("Invalid bootstrap IP " + ip, impossible);
        }
    }

    @PluginMethod
    public void request(PluginCall call) {
        if (client == null) {
            call.reject("Resilient HTTP client is not initialized");
            return;
        }

        String url = call.getString("url");
        String method = call.getString("method", "GET");
        String data = call.getString("data", "");
        JSObject headersObject = call.getObject("headers", new JSObject());

        if (url == null || url.trim().isEmpty()) {
            call.reject("URL is required");
            return;
        }

        try {
            Request.Builder builder = new Request.Builder().url(url);
            Iterator<String> keys = headersObject.keys();
            while (keys.hasNext()) {
                String key = keys.next();
                String value = headersObject.optString(key, "");
                if (!value.isEmpty()) builder.header(key, value);
            }

            String normalizedMethod = method.toUpperCase(Locale.ROOT);
            if ("GET".equals(normalizedMethod) || "HEAD".equals(normalizedMethod)) {
                builder.method(normalizedMethod, null);
            } else {
                String contentType = headersObject.optString("Content-Type", "application/octet-stream");
                MediaType mediaType = MediaType.parse(contentType);
                RequestBody body = RequestBody.create(data == null ? "" : data, mediaType);
                builder.method(normalizedMethod, body);
            }

            client.newCall(builder.build()).enqueue(new Callback() {
                @Override
                public void onFailure(Call okhttpCall, IOException e) {
                    call.reject("Network request failed after resilient DNS: " + e.getMessage(), e);
                }

                @Override
                public void onResponse(Call okhttpCall, Response response) {
                    try (Response res = response) {
                        ResponseBody body = res.body();
                        String text = body != null ? body.string() : "";

                        JSObject result = new JSObject();
                        result.put("status", res.code());
                        result.put("data", text);
                        result.put("url", res.request().url().toString());
                        result.put("dnsMode", lastDnsMode.get());

                        JSObject responseHeaders = new JSObject();
                        Headers headers = res.headers();
                        for (String name : headers.names()) {
                            responseHeaders.put(name, headers.get(name));
                        }
                        result.put("headers", responseHeaders);
                        call.resolve(result);
                    } catch (Exception e) {
                        call.reject("Failed reading HTTP response: " + e.getMessage(), e);
                    }
                }
            });
        } catch (Exception e) {
            call.reject("Failed preparing HTTP request: " + e.getMessage(), e);
        }
    }
}
