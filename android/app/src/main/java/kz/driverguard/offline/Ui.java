package kz.driverguard.offline;

import android.app.Activity;
import android.content.Context;
import android.content.res.ColorStateList;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.text.InputType;
import android.view.View;
import android.widget.*;

/** Shared native visual language: readable cards, generous touch targets and honest state. */
final class Ui {
    static final int BG=0xff0b1020,CARD=0xff151e31,TEXT=0xfff1f5ff,MUTED=0xff98a8c1,
        BLUE=0xff3b82f6,GREEN=0xff4dd6aa,AMBER=0xffffbd69,RED=0xffff707e;
    static int dp(Context c,int n){return Math.round(n*c.getResources().getDisplayMetrics().density);}
    static GradientDrawable shape(Context c,int color,int radius){GradientDrawable d=new GradientDrawable();d.setColor(color);d.setCornerRadius(dp(c,radius));return d;}
    static TextView text(Context c,LinearLayout parent,String value,int size,int color){
        TextView t=new TextView(c);t.setText(value);t.setTextSize(size);t.setTextColor(color);
        t.setFontFeatureSettings("kern");t.setLineSpacing(dp(c,3),1);t.setPadding(0,dp(c,5),0,dp(c,5));
        if(size>=21)t.setTypeface(Typeface.create("sans-serif",Typeface.BOLD));parent.addView(t);return t;
    }
    static LinearLayout card(Context c,LinearLayout parent){
        LinearLayout b=new LinearLayout(c);b.setOrientation(LinearLayout.VERTICAL);b.setPadding(dp(c,18),dp(c,14),dp(c,18),dp(c,16));
        b.setBackground(shape(c,CARD,22));LinearLayout.LayoutParams p=new LinearLayout.LayoutParams(-1,-2);p.setMargins(0,dp(c,9),0,dp(c,9));parent.addView(b,p);return b;
    }
    static Button button(Context c,LinearLayout parent,String title,Runnable action){
        Button b=new Button(c);b.setText(title);b.setAllCaps(false);b.setTextSize(16);b.setTypeface(Typeface.create("sans-serif-medium",Typeface.NORMAL));b.setTextColor(TEXT);
        b.setBackgroundTintList(ColorStateList.valueOf(BLUE));b.setBackground(shape(c,BLUE,14));
        b.setMinHeight(dp(c,54));b.setPadding(dp(c,12),dp(c,9),dp(c,12),dp(c,9));
        LinearLayout.LayoutParams p=new LinearLayout.LayoutParams(-1,-2);p.setMargins(0,dp(c,6),0,dp(c,6));parent.addView(b,p);b.setOnClickListener(v->action.run());return b;
    }
    static Button secondary(Context c,LinearLayout parent,String title,Runnable action){Button b=button(c,parent,title,action);b.setBackgroundTintList(ColorStateList.valueOf(0xff23314b));return b;}
    static EditText field(Context c,LinearLayout parent,String hint,String value,boolean secret){
        EditText e=new EditText(c);e.setText(value);e.setHint(hint);e.setTextColor(TEXT);e.setHintTextColor(MUTED);e.setTextSize(16);e.setSingleLine();
        e.setBackground(shape(c,0xff23314b,12));e.setPadding(dp(c,14),dp(c,14),dp(c,14),dp(c,14));
        e.setInputType(secret?InputType.TYPE_CLASS_TEXT|InputType.TYPE_TEXT_VARIATION_PASSWORD:InputType.TYPE_CLASS_TEXT|InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS);
        e.setSaveEnabled(!secret);if(secret)e.setImportantForAutofill(View.IMPORTANT_FOR_AUTOFILL_NO);
        LinearLayout.LayoutParams p=new LinearLayout.LayoutParams(-1,-2);p.setMargins(0,dp(c,5),0,dp(c,9));parent.addView(e,p);return e;
    }
    static LinearLayout page(Activity a,String title,String subtitle){
        a.getWindow().setStatusBarColor(BG);a.getWindow().setNavigationBarColor(BG);
        ScrollView scroll=new ScrollView(a);scroll.setFillViewport(true);scroll.setBackgroundColor(BG);scroll.setClipToPadding(false);
        LinearLayout b=new LinearLayout(a);b.setOrientation(LinearLayout.VERTICAL);b.setPadding(dp(a,20),dp(a,18),dp(a,20),dp(a,24));scroll.addView(b);a.setContentView(scroll);
        scroll.setOnApplyWindowInsetsListener((v,i)->{scroll.setPadding(0,i.getSystemWindowInsetTop(),0,i.getSystemWindowInsetBottom());return i;});
        text(a,b,"DRIVERGUARD  /  ВОДИТЕЛЬ",11,BLUE).setLetterSpacing(.10f);
        text(a,b,title,30,TEXT);if(subtitle!=null&&!subtitle.isBlank())text(a,b,subtitle,14,MUTED);return b;
    }
}
